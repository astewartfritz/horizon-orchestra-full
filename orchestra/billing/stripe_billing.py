from __future__ import annotations

"""
Stripe billing system for Horizon Orchestra.

Handles subscriptions, usage metering, invoices, and Stripe webhooks
for a SaaS platform. All Stripe API calls are made directly via httpx
(no stripe SDK dependency) using Basic auth with the secret key.
"""

__all__ = [
    "StripeBilling",
    "BillingConfig",
    "Subscription",
    "UsageMeter",
    "Invoice",
    "PricingTier",
    "PRICING_TIERS",
]

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing tiers
# ---------------------------------------------------------------------------

@dataclass
class PricingTier:
    """Represents a single pricing tier."""

    name: str
    stripe_price_id: str
    monthly_price: float  # USD per month (0 = free, -1 = custom/enterprise)
    annual_price: float   # USD per month when billed annually (-1 = custom)
    features: list[str]
    limits: dict[str, int | float]  # max_requests_per_day, max_tokens_per_month, etc.


PRICING_TIERS: dict[str, PricingTier] = {
    "free": PricingTier(
        name="free",
        stripe_price_id="price_free",
        monthly_price=0.0,
        annual_price=0.0,
        features=[
            "Architecture A — Monolithic Orchestrator",
            "50 requests per day",
            "100K tokens per month",
            "50 tool calls per run",
            "1 agent",
            "3 connectors",
            "1 GB storage",
            "Streaming output",
            "Community support",
        ],
        limits={
            "max_requests_per_day": 50,
            "max_tokens_per_month": 100_000,
            "max_agents": 1,
            "max_connectors": 3,
            "max_storage_gb": 1,
            "architectures": ["A"],
        },
    ),
    "pro": PricingTier(
        name="pro",
        stripe_price_id=os.environ.get("STRIPE_PRO_PRICE_ID", "price_pro_monthly"),
        monthly_price=20.0,
        annual_price=17.0,
        features=[
            "Architectures A + B — Monolithic + RAG Pipeline",
            "500 requests per day",
            "2M tokens per month",
            "200 tool calls per run (A) / 100 per run (B)",
            "Multi-hop research with citation verification",
            "10 sources per query, 2 citation hops",
            "50 research runs per day",
            "1-hour long-horizon tasks",
            "5 agents",
            "All connectors",
            "10 GB storage",
            "Priority support",
            "Advanced analytics",
        ],
        limits={
            "max_requests_per_day": 500,
            "max_tokens_per_month": 2_000_000,
            "max_agents": 5,
            "max_connectors": -1,
            "max_storage_gb": 10,
            "architectures": ["A", "B"],
        },
    ),
    "team": PricingTier(
        name="team",
        stripe_price_id=os.environ.get("STRIPE_TEAM_PRICE_ID", "price_team_monthly"),
        monthly_price=25.0,   # per seat
        annual_price=20.0,    # per seat
        features=[
            "Architectures A + B + C — Monolithic + RAG + Agent Swarm",
            "1000 requests per day per seat",
            "10M tokens per month",
            "300 tool calls per run (A) / 200 (B) / 500 (C)",
            "20 sub-agents, 10 parallel",
            "20 sources per query, 3 citation hops",
            "200 research runs per day",
            "2-hour long-horizon tasks (3 concurrent)",
            "20 agents",
            "All connectors",
            "50 GB storage",
            "Admin tools & user management",
            "Audit logs",
            "SSO (SAML/OIDC)",
            "Dedicated Slack support",
        ],
        limits={
            "max_requests_per_day": 1000,
            "max_tokens_per_month": 10_000_000,
            "max_agents": 20,
            "max_connectors": -1,
            "max_storage_gb": 50,
            "architectures": ["A", "B", "C"],
        },
    ),
    "max": PricingTier(
        name="max",
        stripe_price_id=os.environ.get("STRIPE_MAX_PRICE_ID", "price_max_250"),
        monthly_price=250.0,
        annual_price=2500.0,
        features=[
            "All Architectures — A + B + C + D + E",
            "Unlimited requests & tokens",
            "Unlimited tool calls",
            "100 parallel swarm agents",
            "Unlimited MCP server connections",
            "Unlimited sources, citation hops, research runs",
            "4-hour long-horizon tasks (10 concurrent)",
            "Full production deployment (Architecture E)",
            "All connectors",
            "1TB storage",
            "SSO (SAML/OIDC)",
            "Dedicated support",
            "99.9% SLA",
            "Priority GPU access",
            "Custom model fine-tuning",
            "On-premise deployment option",
            "HIPAA / SOC2 compliance",
        ],
        limits={
            "max_requests_per_day": -1,
            "max_tokens_per_month": -1,
            "max_agents": -1,
            "max_connectors": -1,
            "max_storage_gb": 1000,
            "architectures": ["A", "B", "C", "D", "E"],
        },
    ),
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class BillingConfig:
    """Configuration for the StripeBilling system."""

    stripe_api_key: str = field(
        default_factory=lambda: os.environ.get("STRIPE_SECRET_KEY", "")
    )
    stripe_webhook_secret: str = field(
        default_factory=lambda: os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    )
    pricing_tiers: dict[str, PricingTier] = field(default_factory=lambda: dict(PRICING_TIERS))
    currency: str = "usd"
    tax_rate: float = 0.0


@dataclass
class Subscription:
    """Represents a user's subscription."""

    id: str
    user_id: str
    tier: str
    stripe_customer_id: str
    stripe_subscription_id: str
    status: str  # active | past_due | canceled | trialing
    current_period_start: datetime
    current_period_end: datetime
    cancel_at_period_end: bool
    created_at: datetime


@dataclass
class UsageMeter:
    """Tracks resource usage for a billing period."""

    user_id: str
    period_start: datetime
    requests_used: int = 0
    tokens_used: int = 0
    agents_spawned: int = 0
    storage_used_mb: float = 0.0


@dataclass
class Invoice:
    """Represents a Stripe invoice."""

    id: str
    user_id: str
    stripe_invoice_id: str
    amount: float        # in dollars
    currency: str
    status: str          # draft | open | paid | uncollectible | void
    period_start: datetime
    period_end: datetime
    line_items: list[dict[str, Any]]
    paid_at: datetime | None
    pdf_url: str | None


# ---------------------------------------------------------------------------
# Stripe HTTP client helpers
# ---------------------------------------------------------------------------

STRIPE_BASE = "https://api.stripe.com/v1"


def _stripe_auth(api_key: str) -> httpx.BasicAuth:
    return httpx.BasicAuth(username=api_key, password="")


def _encode_form(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Recursively flatten a dict into Stripe's form-encoded format."""
    result: dict[str, str] = {}
    for key, value in data.items():
        full_key = f"{prefix}[{key}]" if prefix else key
        if isinstance(value, dict):
            result.update(_encode_form(value, full_key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    result.update(_encode_form(item, f"{full_key}[{i}]"))
                else:
                    result[f"{full_key}[{i}]"] = str(item)
        elif value is not None:
            result[full_key] = str(value).lower() if isinstance(value, bool) else str(value)
    return result


# ---------------------------------------------------------------------------
# StripeBilling
# ---------------------------------------------------------------------------

class StripeBilling:
    """
    Full Stripe billing integration for Horizon Orchestra.

    Usage is tracked in-memory (swap to DynamoDB/Redis in production
    via CloudState). All Stripe API calls use httpx with Basic auth.
    """

    def __init__(self, config: BillingConfig) -> None:
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=STRIPE_BASE,
            auth=_stripe_auth(config.stripe_api_key),
            timeout=30.0,
        )
        # In-memory storage (replace with persistent store in production)
        self._subscriptions: dict[str, Subscription] = {}          # user_id -> Subscription
        self._usage: dict[str, UsageMeter] = {}                    # user_id -> UsageMeter
        self._customer_map: dict[str, str] = {}                    # user_id -> stripe_customer_id
        logger.info("StripeBilling initialised (currency=%s)", config.currency)

    # ------------------------------------------------------------------
    # Customer management
    # ------------------------------------------------------------------

    async def create_customer(self, user_id: str, email: str, name: str) -> dict[str, Any]:
        """Create a Stripe Customer object and cache the mapping."""
        logger.info("Creating Stripe customer for user_id=%s email=%s", user_id, email)
        payload = _encode_form({
            "email": email,
            "name": name,
            "metadata": {"user_id": user_id},
        })
        resp = await self._client.post("/customers", data=payload)
        resp.raise_for_status()
        customer = resp.json()
        self._customer_map[user_id] = customer["id"]
        logger.debug("Stripe customer created: %s", customer["id"])
        return customer

    # ------------------------------------------------------------------
    # Subscriptions
    # ------------------------------------------------------------------

    async def create_subscription(
        self, user_id: str, tier: str, stripe_customer_id: str
    ) -> Subscription:
        """Create a Stripe subscription for the given tier."""
        pricing = self._get_tier(tier)
        logger.info("Creating subscription tier=%s for user_id=%s", tier, user_id)

        # Free tier: create a local record without a real Stripe subscription
        if pricing.monthly_price == 0.0:
            now = datetime.now(tz=timezone.utc)
            sub = Subscription(
                id=str(uuid.uuid4()),
                user_id=user_id,
                tier=tier,
                stripe_customer_id=stripe_customer_id,
                stripe_subscription_id="",
                status="active",
                current_period_start=now,
                current_period_end=datetime(
                    now.year + (1 if now.month == 12 else 0),
                    (now.month % 12) + 1,
                    now.day,
                    tzinfo=timezone.utc,
                ),
                cancel_at_period_end=False,
                created_at=now,
            )
            self._subscriptions[user_id] = sub
            return sub

        payload = _encode_form({
            "customer": stripe_customer_id,
            "items": [{"price": pricing.stripe_price_id}],
            "metadata": {"user_id": user_id, "tier": tier},
        })
        resp = await self._client.post("/subscriptions", data=payload)
        resp.raise_for_status()
        data = resp.json()

        sub = self._parse_stripe_subscription(user_id, tier, stripe_customer_id, data)
        self._subscriptions[user_id] = sub
        logger.info("Subscription created: stripe_id=%s", sub.stripe_subscription_id)
        return sub

    async def cancel_subscription(
        self, subscription_id: str, immediately: bool = False
    ) -> dict[str, Any]:
        """Cancel a Stripe subscription immediately or at period end."""
        logger.info(
            "Cancelling subscription=%s immediately=%s", subscription_id, immediately
        )
        if immediately:
            resp = await self._client.delete(f"/subscriptions/{subscription_id}")
        else:
            payload = _encode_form({"cancel_at_period_end": True})
            resp = await self._client.post(
                f"/subscriptions/{subscription_id}", data=payload
            )
        resp.raise_for_status()
        data = resp.json()

        # Update local cache
        for sub in self._subscriptions.values():
            if sub.stripe_subscription_id == subscription_id:
                sub.status = "canceled" if immediately else sub.status
                sub.cancel_at_period_end = not immediately

        return data

    async def change_tier(self, subscription_id: str, new_tier: str) -> dict[str, Any]:
        """Upgrade or downgrade a subscription to a new tier."""
        new_pricing = self._get_tier(new_tier)
        logger.info(
            "Changing subscription=%s to tier=%s", subscription_id, new_tier
        )

        # First, retrieve current subscription to get item ID
        resp = await self._client.get(f"/subscriptions/{subscription_id}")
        resp.raise_for_status()
        current = resp.json()
        item_id = current["items"]["data"][0]["id"]

        payload = _encode_form({
            "items": [{"id": item_id, "price": new_pricing.stripe_price_id}],
            "proration_behavior": "create_prorations",
            "metadata": {"tier": new_tier},
        })
        resp = await self._client.post(
            f"/subscriptions/{subscription_id}", data=payload
        )
        resp.raise_for_status()
        data = resp.json()

        # Update local cache
        for uid, sub in self._subscriptions.items():
            if sub.stripe_subscription_id == subscription_id:
                sub.tier = new_tier
                self._subscriptions[uid] = sub

        logger.info("Tier change complete: subscription=%s new_tier=%s", subscription_id, new_tier)
        return data

    async def get_subscription(self, user_id: str) -> Subscription | None:
        """Return the cached subscription for a user, refreshing from Stripe if needed."""
        sub = self._subscriptions.get(user_id)
        if sub is None:
            return None

        # Refresh status from Stripe for paid tiers
        if sub.stripe_subscription_id:
            try:
                resp = await self._client.get(
                    f"/subscriptions/{sub.stripe_subscription_id}"
                )
                if resp.status_code == 200:
                    data = resp.json()
                    sub.status = data.get("status", sub.status)
                    sub.cancel_at_period_end = data.get(
                        "cancel_at_period_end", sub.cancel_at_period_end
                    )
                    self._subscriptions[user_id] = sub
            except httpx.HTTPError as exc:
                logger.warning("Failed to refresh subscription from Stripe: %s", exc)

        return sub

    # ------------------------------------------------------------------
    # Usage metering
    # ------------------------------------------------------------------

    async def record_usage(
        self,
        user_id: str,
        requests: int = 0,
        tokens: int = 0,
        agents: int = 0,
    ) -> UsageMeter:
        """Increment usage counters for a user in the current billing period."""
        meter = self._usage.get(user_id)
        if meter is None:
            meter = UsageMeter(
                user_id=user_id,
                period_start=datetime.now(tz=timezone.utc),
            )
        meter.requests_used += requests
        meter.tokens_used += tokens
        meter.agents_spawned += agents
        self._usage[user_id] = meter
        logger.debug(
            "Usage recorded user_id=%s requests=%d tokens=%d agents=%d",
            user_id, requests, tokens, agents,
        )
        return meter

    async def check_limits(self, user_id: str) -> dict[str, Any]:
        """
        Check whether a user is within their tier's limits.

        Returns:
            {
                "allowed": bool,
                "reason": str,
                "usage": dict,
                "limits": dict,
            }
        """
        sub = await self.get_subscription(user_id)
        tier_name = sub.tier if sub else "free"
        tier = self._get_tier(tier_name)
        meter = self._usage.get(user_id) or UsageMeter(
            user_id=user_id, period_start=datetime.now(tz=timezone.utc)
        )

        limits = tier.limits
        usage = {
            "requests_used_today": meter.requests_used,
            "tokens_used_this_month": meter.tokens_used,
            "agents_active": meter.agents_spawned,
            "storage_used_mb": meter.storage_used_mb,
        }

        # -1 means unlimited
        checks = [
            (
                "max_requests_per_day",
                meter.requests_used,
                "Daily request limit reached",
            ),
            (
                "max_tokens_per_month",
                meter.tokens_used,
                "Monthly token limit reached",
            ),
            (
                "max_agents",
                meter.agents_spawned,
                "Maximum concurrent agents reached",
            ),
        ]

        for limit_key, used, reason_msg in checks:
            limit_val = limits.get(limit_key, -1)
            if limit_val != -1 and used >= limit_val:
                return {
                    "allowed": False,
                    "reason": f"{reason_msg}. Upgrade to a higher plan.",
                    "usage": usage,
                    "limits": limits,
                }

        return {
            "allowed": True,
            "reason": "Within limits",
            "usage": usage,
            "limits": limits,
        }

    # ------------------------------------------------------------------
    # Invoices
    # ------------------------------------------------------------------

    async def get_invoices(self, user_id: str, limit: int = 10) -> list[Invoice]:
        """Fetch the last N invoices for a user from Stripe."""
        customer_id = self._customer_map.get(user_id)
        if not customer_id:
            sub = self._subscriptions.get(user_id)
            customer_id = sub.stripe_customer_id if sub else None

        if not customer_id:
            logger.warning("No Stripe customer found for user_id=%s", user_id)
            return []

        resp = await self._client.get(
            "/invoices",
            params={"customer": customer_id, "limit": str(limit)},
        )
        resp.raise_for_status()
        data = resp.json()

        invoices: list[Invoice] = []
        for raw in data.get("data", []):
            invoices.append(self._parse_stripe_invoice(user_id, raw))
        return invoices

    # ------------------------------------------------------------------
    # Checkout & Portal
    # ------------------------------------------------------------------

    async def create_checkout_session(
        self,
        user_id: str,
        tier: str,
        success_url: str,
        cancel_url: str,
    ) -> dict[str, Any]:
        """Create a Stripe Checkout session for self-service signup/upgrade."""
        pricing = self._get_tier(tier)
        customer_id = self._customer_map.get(user_id)

        payload: dict[str, Any] = {
            "mode": "subscription",
            "line_items": [{"price": pricing.stripe_price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"user_id": user_id, "tier": tier},
        }
        if customer_id:
            payload["customer"] = customer_id

        resp = await self._client.post(
            "/checkout/sessions", data=_encode_form(payload)
        )
        resp.raise_for_status()
        session = resp.json()
        logger.info(
            "Checkout session created: id=%s user_id=%s tier=%s",
            session.get("id"), user_id, tier,
        )
        return session

    async def create_portal_session(
        self,
        stripe_customer_id: str,
        return_url: str,
    ) -> dict[str, Any]:
        """Create a Stripe Customer Portal session for self-service management."""
        payload = _encode_form({
            "customer": stripe_customer_id,
            "return_url": return_url,
        })
        resp = await self._client.post("/billing_portal/sessions", data=payload)
        resp.raise_for_status()
        session = resp.json()
        logger.info(
            "Portal session created for customer=%s", stripe_customer_id
        )
        return session

    # ------------------------------------------------------------------
    # Webhook handling
    # ------------------------------------------------------------------

    async def handle_webhook(
        self, payload: bytes, signature: str
    ) -> dict[str, Any]:
        """
        Verify and process a Stripe webhook event.

        Handles:
        - invoice.paid
        - customer.subscription.updated
        - customer.subscription.deleted
        - checkout.session.completed
        """
        # Verify webhook signature
        if self._config.stripe_webhook_secret:
            if not self._verify_webhook_signature(payload, signature):
                logger.warning("Webhook signature verification failed")
                return {"status": "error", "message": "Invalid signature"}

        try:
            event = json.loads(payload)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse webhook payload: %s", exc)
            return {"status": "error", "message": "Invalid JSON"}

        event_type = event.get("type", "")
        event_data = event.get("data", {}).get("object", {})
        logger.info("Processing webhook event: %s", event_type)

        if event_type == "invoice.paid":
            return await self._handle_invoice_paid(event_data)
        elif event_type == "customer.subscription.updated":
            return await self._handle_subscription_updated(event_data)
        elif event_type == "customer.subscription.deleted":
            return await self._handle_subscription_deleted(event_data)
        elif event_type == "checkout.session.completed":
            return await self._handle_checkout_completed(event_data)
        else:
            logger.debug("Unhandled webhook event type: %s", event_type)
            return {"status": "ignored", "event_type": event_type}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_tier(self, name: str) -> PricingTier:
        """Look up a pricing tier by name, raising ValueError if not found."""
        tier = self._config.pricing_tiers.get(name)
        if tier is None:
            raise ValueError(
                f"Unknown pricing tier '{name}'. "
                f"Valid tiers: {list(self._config.pricing_tiers.keys())}"
            )
        return tier

    def _parse_stripe_subscription(
        self,
        user_id: str,
        tier: str,
        stripe_customer_id: str,
        data: dict[str, Any],
    ) -> Subscription:
        """Convert a raw Stripe subscription dict to a Subscription dataclass."""
        return Subscription(
            id=str(uuid.uuid4()),
            user_id=user_id,
            tier=tier,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=data["id"],
            status=data.get("status", "active"),
            current_period_start=datetime.fromtimestamp(
                data.get("current_period_start", time.time()), tz=timezone.utc
            ),
            current_period_end=datetime.fromtimestamp(
                data.get("current_period_end", time.time() + 2592000), tz=timezone.utc
            ),
            cancel_at_period_end=data.get("cancel_at_period_end", False),
            created_at=datetime.fromtimestamp(
                data.get("created", time.time()), tz=timezone.utc
            ),
        )

    def _parse_stripe_invoice(
        self, user_id: str, data: dict[str, Any]
    ) -> Invoice:
        """Convert a raw Stripe invoice dict to an Invoice dataclass."""
        paid_at_ts = data.get("status_transitions", {}).get("paid_at")
        return Invoice(
            id=str(uuid.uuid4()),
            user_id=user_id,
            stripe_invoice_id=data["id"],
            amount=data.get("amount_paid", 0) / 100.0,
            currency=data.get("currency", "usd"),
            status=data.get("status", "draft"),
            period_start=datetime.fromtimestamp(
                data.get("period_start", time.time()), tz=timezone.utc
            ),
            period_end=datetime.fromtimestamp(
                data.get("period_end", time.time()), tz=timezone.utc
            ),
            line_items=[
                {
                    "description": line.get("description", ""),
                    "amount": line.get("amount", 0) / 100.0,
                    "currency": line.get("currency", "usd"),
                    "quantity": line.get("quantity", 1),
                }
                for line in data.get("lines", {}).get("data", [])
            ],
            paid_at=(
                datetime.fromtimestamp(paid_at_ts, tz=timezone.utc)
                if paid_at_ts
                else None
            ),
            pdf_url=data.get("invoice_pdf"),
        )

    def _verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify Stripe webhook signature using HMAC-SHA256."""
        try:
            # Parse the Stripe-Signature header
            parts = {
                kv.split("=")[0]: kv.split("=")[1]
                for kv in signature.split(",")
                if "=" in kv
            }
            timestamp = parts.get("t", "")
            v1 = parts.get("v1", "")

            signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
            expected = hmac.new(
                self._config.stripe_webhook_secret.encode("utf-8"),
                signed_payload.encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(expected, v1)
        except Exception as exc:  # noqa: BLE001
            logger.error("Webhook signature error: %s", exc)
            return False

    async def _handle_invoice_paid(self, data: dict[str, Any]) -> dict[str, Any]:
        """Handle invoice.paid webhook — reset usage meters for new period."""
        customer_id = data.get("customer", "")
        logger.info("Invoice paid for customer=%s", customer_id)

        # Find user by customer ID and reset usage
        for uid, sub in self._subscriptions.items():
            if sub.stripe_customer_id == customer_id:
                self._usage[uid] = UsageMeter(
                    user_id=uid,
                    period_start=datetime.now(tz=timezone.utc),
                )
                logger.info("Usage meter reset for user_id=%s", uid)

        return {"status": "ok", "event": "invoice.paid"}

    async def _handle_subscription_updated(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle customer.subscription.updated webhook."""
        stripe_sub_id = data.get("id", "")
        new_status = data.get("status", "")
        cancel_at_end = data.get("cancel_at_period_end", False)

        for uid, sub in self._subscriptions.items():
            if sub.stripe_subscription_id == stripe_sub_id:
                sub.status = new_status
                sub.cancel_at_period_end = cancel_at_end
                # Update period dates
                if "current_period_start" in data:
                    sub.current_period_start = datetime.fromtimestamp(
                        data["current_period_start"], tz=timezone.utc
                    )
                if "current_period_end" in data:
                    sub.current_period_end = datetime.fromtimestamp(
                        data["current_period_end"], tz=timezone.utc
                    )
                self._subscriptions[uid] = sub
                logger.info(
                    "Subscription updated: user_id=%s status=%s", uid, new_status
                )

        return {"status": "ok", "event": "customer.subscription.updated"}

    async def _handle_subscription_deleted(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle customer.subscription.deleted — downgrade to free tier."""
        stripe_sub_id = data.get("id", "")

        for uid, sub in self._subscriptions.items():
            if sub.stripe_subscription_id == stripe_sub_id:
                sub.status = "canceled"
                sub.tier = "free"
                sub.stripe_subscription_id = ""
                self._subscriptions[uid] = sub
                logger.info(
                    "Subscription deleted: user_id=%s, downgraded to free", uid
                )

        return {"status": "ok", "event": "customer.subscription.deleted"}

    async def _handle_checkout_completed(
        self, data: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle checkout.session.completed — provision the subscription."""
        user_id = data.get("metadata", {}).get("user_id", "")
        tier = data.get("metadata", {}).get("tier", "free")
        stripe_customer_id = data.get("customer", "")
        stripe_sub_id = data.get("subscription", "")

        if user_id and stripe_sub_id:
            # Fetch the full subscription details from Stripe
            try:
                resp = await self._client.get(f"/subscriptions/{stripe_sub_id}")
                if resp.status_code == 200:
                    sub_data = resp.json()
                    sub = self._parse_stripe_subscription(
                        user_id, tier, stripe_customer_id, sub_data
                    )
                    self._subscriptions[user_id] = sub
                    self._customer_map[user_id] = stripe_customer_id
                    logger.info(
                        "Checkout completed: provisioned %s subscription for user_id=%s",
                        tier, user_id,
                    )
            except httpx.HTTPError as exc:
                logger.error(
                    "Failed to fetch subscription after checkout: %s", exc
                )

        return {"status": "ok", "event": "checkout.session.completed"}

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
