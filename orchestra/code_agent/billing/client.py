"""Stripe API wrapper for Orchestra billing."""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("orchestra.billing")

PLAN_NAME = "Orchestra Pro"
PLAN_AMOUNT = 5000        # $50.00 in cents
PLAN_CURRENCY = "usd"
PLAN_INTERVAL = "month"


class StripeClient:
    _instance: StripeClient | None = None

    def __init__(self) -> None:
        import stripe
        self._stripe = stripe
        self._stripe.api_key = os.environ.get("STRIPE_SECRET_KEY", "")
        self._price_id: str = os.environ.get("STRIPE_PRICE_ID", "")
        self._webhook_secret: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        self._pub_key: str = os.environ.get("STRIPE_PUBLISHABLE_KEY", "")

    @classmethod
    def get(cls) -> StripeClient:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def configured(self) -> bool:
        return bool(self._stripe.api_key)

    @property
    def publishable_key(self) -> str:
        return self._pub_key

    # ── Price ────────────────────────────────────────────────────────────────

    def get_or_create_price(self) -> str:
        """Return the $50/month Price ID, creating the product+price if needed."""
        if self._price_id:
            return self._price_id

        # Search for existing Orchestra Pro price
        prices = self._stripe.Price.list(active=True, limit=100)
        for price in prices.auto_paging_iter():
            if (
                price.unit_amount == PLAN_AMOUNT
                and price.currency == PLAN_CURRENCY
                and price.recurring
                and price.recurring.interval == PLAN_INTERVAL
            ):
                prod = self._stripe.Product.retrieve(price.product)
                if prod.name == PLAN_NAME:
                    self._price_id = price.id
                    return self._price_id

        # Create product + price
        product = self._stripe.Product.create(
            name=PLAN_NAME,
            description="Full Orchestra agent execution — autonomous code changes, MCP tools, all engines",
        )
        price = self._stripe.Price.create(
            product=product.id,
            unit_amount=PLAN_AMOUNT,
            currency=PLAN_CURRENCY,
            recurring={"interval": PLAN_INTERVAL},
        )
        self._price_id = price.id
        log.info("Created Stripe price %s ($50/mo)", self._price_id)
        return self._price_id

    # ── Customer ─────────────────────────────────────────────────────────────

    def get_or_create_customer(self, local_id: str, email: str = "") -> str:
        """Return Stripe customer ID for a local anonymous ID."""
        from orchestra.code_agent.billing.store import SubscriptionStore
        store = SubscriptionStore.get()

        existing = store.stripe_id_for_local(local_id)
        if existing:
            return existing

        kwargs: dict[str, Any] = {
            "metadata": {"orchestra_local_id": local_id},
        }
        if email:
            kwargs["email"] = email
        customer = self._stripe.Customer.create(**kwargs)
        store.link_stripe_customer(local_id, customer.id)
        return customer.id

    # ── Checkout ─────────────────────────────────────────────────────────────

    def create_checkout_session(
        self,
        local_id: str,
        email: str = "",
        success_url: str = "",
        cancel_url: str = "",
    ) -> str:
        """Create a Stripe Checkout session and return the URL."""
        price_id = self.get_or_create_price()
        customer_id = self.get_or_create_customer(local_id, email)

        session = self._stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url or "http://localhost:8000/billing?success=1",
            cancel_url=cancel_url or "http://localhost:8000/billing",
            subscription_data={
                "metadata": {"orchestra_local_id": local_id},
            },
            allow_promotion_codes=True,
            billing_address_collection="auto",
        )
        return session.url

    # ── Customer Portal ───────────────────────────────────────────────────────

    def create_portal_session(self, local_id: str, return_url: str = "") -> str:
        """Create a Stripe Customer Portal session and return the URL."""
        customer_id = self.get_or_create_customer(local_id)
        session = self._stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=return_url or "http://localhost:8000/billing",
        )
        return session.url

    # ── Webhooks ─────────────────────────────────────────────────────────────

    def construct_event(self, payload: bytes, sig_header: str) -> Any:
        return self._stripe.Webhook.construct_event(
            payload, sig_header, self._webhook_secret
        )

    def handle_webhook_event(self, event: Any) -> None:
        from orchestra.code_agent.billing.store import SubscriptionStore
        store = SubscriptionStore.get()

        etype = event["type"]
        obj = event["data"]["object"]

        if etype in (
            "customer.subscription.created",
            "customer.subscription.updated",
            "customer.subscription.deleted",
        ):
            store.upsert_subscription(obj)
            log.info("Subscription %s → %s", obj["id"], obj["status"])

        elif etype == "checkout.session.completed":
            cus_id = obj.get("customer")
            local_id = obj.get("metadata", {}).get("orchestra_local_id")
            if cus_id and local_id:
                store.link_stripe_customer(local_id, cus_id)
            # Subscription will arrive via customer.subscription.created
