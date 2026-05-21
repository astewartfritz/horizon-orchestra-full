"""Unified production-grade billing manager for Horizon Orchestra.

Delegates to ``BillingScaffold`` (which already bridges the two legacy
billing implementations) and marks the following as **deprecated**:

* ``orchestra.stripe_billing`` — SDK-based ``BillingManager``
* ``orchestra.billing.stripe_billing`` — httpx-based ``StripeBilling``

Usage::

    from orchestra.code_agent.billing.manager import BillingManager

    mgr = BillingManager(stripe_api_key="sk_test_...")
    customer = await mgr.create_customer("alice@example.com", "Alice")
    sub = await mgr.create_subscription(customer["id"], tier="pro")
    ok = await mgr.check_entitlement("user-1", action="llm_inference")
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any

log = logging.getLogger(__name__)

__all__ = [
    "BillingManager",
    "NullBillingManager",
]

# ---------------------------------------------------------------------------
# Try to load the real scaffold — wraps both legacy billing implementations
# ---------------------------------------------------------------------------

try:
    from orchestra.billing.scaffold import BillingScaffold as _BillingScaffold
    from orchestra.billing.scaffold import ScaffoldConfig as _ScaffoldConfig

    HAS_SCAFFOLD = True
except ImportError:
    _BillingScaffold = None  # type: ignore[assignment]
    _ScaffoldConfig = None  # type: ignore[assignment]
    HAS_SCAFFOLD = False


# ---------------------------------------------------------------------------
# NullBillingManager — no-op fallback for development / testing
# ---------------------------------------------------------------------------

class NullBillingManager:
    """No-op billing manager for development and testing.

    All methods accept the same signatures as :class:`BillingManager` but
    return sensible defaults without any network, database, or Stripe calls.
    """

    def __init__(self, stripe_api_key: str = "", db_path: str = "orchestra_billing.db") -> None:
        self._api_key: str = stripe_api_key or os.environ.get("STRIPE_SECRET_KEY", "")
        self._db_path: str = db_path

    def is_ready(self) -> bool:
        return False

    async def create_customer(self, email: str, name: str) -> dict[str, Any]:
        cid = f"null_{uuid.uuid4().hex[:12]}"
        return {"id": cid, "email": email, "name": name, "tier": "free"}

    async def create_subscription(self, customer_id: str, tier: str = "pro") -> dict[str, Any]:
        return {
            "id": f"sub_null_{uuid.uuid4().hex[:12]}",
            "customer_id": customer_id,
            "tier": tier,
            "status": "active",
        }

    async def cancel_subscription(self, subscription_id: str) -> bool:
        return True

    async def change_tier(self, subscription_id: str, new_tier: str) -> bool:
        return True

    async def check_entitlement(self, user_id: str, action: str) -> bool:
        return True

    async def record_usage(self, customer_id: str, usage_type: str, value: float) -> bool:
        return True

    async def get_usage_summary(self, customer_id: str) -> dict[str, Any]:
        return {"customer_id": customer_id, "usage": {}, "period": "current"}

    async def create_checkout_session(self, tier: str, customer_id: str | None = None) -> dict[str, Any]:
        return {"url": "http://localhost:8000/billing", "session_id": "null_session"}

    async def create_portal_session(self, customer_id: str) -> dict[str, Any]:
        return {"url": "http://localhost:8000/billing", "session_id": "null_portal"}

    async def handle_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        return {"status": "ignored", "event_type": "null"}


# ---------------------------------------------------------------------------
# BillingManager — unified entry point that delegates to BillingScaffold
# ---------------------------------------------------------------------------

class BillingManager:
    """Production-grade billing manager for Horizon Orchestra.

    Internally creates a :class:`~orchestra.billing.scaffold.BillingScaffold`
    which bridges the two legacy billing implementations.  When the scaffold
    is unavailable (missing dependencies, no API key) falls back to in-memory
    mock suitable for local development.

    Parameters
    ----------
    stripe_api_key:
        Stripe secret key (``sk_live_*`` / ``sk_test_*``).  If omitted,
        reads from the ``STRIPE_SECRET_KEY`` environment variable.
    db_path:
        Filesystem path for the SQLite database used by
        :class:`~orchestra.code_agent.billing.store.SubscriptionStore`.
    """

    def __init__(self, stripe_api_key: str = "", db_path: str = "orchestra_billing.db") -> None:
        self._api_key: str = stripe_api_key or os.environ.get("STRIPE_SECRET_KEY", "")
        self._webhook_secret: str = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
        self._db_path: str = db_path
        self._ready: bool = False
        self._scaffold: _BillingScaffold | None = None

        # ID mapping caches (bridges subscription_id ↔ user_id)
        self._sub_to_user: dict[str, str] = {}
        self._cus_to_user: dict[str, str] = {}

        if HAS_SCAFFOLD and self._api_key:
            try:
                config = _ScaffoldConfig(
                    stripe_api_key=self._api_key,
                    stripe_webhook_secret=self._webhook_secret,
                )
                self._scaffold = _BillingScaffold(config)
                self._ready = True
                log.info("BillingManager initialised with real Stripe scaffold")
            except Exception as exc:
                log.warning("Failed to initialise BillingScaffold: %s", exc)

        if not self._ready:
            log.info("BillingManager running in offline/mock mode (scaffold unavailable)")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        """``True`` if the underlying ``BillingScaffold`` loaded successfully."""
        return self._ready

    # ------------------------------------------------------------------
    # Customer management
    # ------------------------------------------------------------------

    async def create_customer(self, email: str, name: str) -> dict[str, Any]:
        """Create a new customer and return their info.

        Returns a dict with ``id``, ``email``, ``name``, and ``user_id`` keys.
        """
        user_id = f"user_{uuid.uuid4().hex[:8]}"
        if self._ready and self._scaffold:
            result = await self._scaffold.ensure_customer(user_id, email, name)
            cid = result.get("id", user_id)
            self._cus_to_user[cid] = user_id
            return {"id": cid, "email": email, "name": name, "user_id": user_id}
        cid = f"cus_offline_{uuid.uuid4().hex[:12]}"
        self._cus_to_user[cid] = user_id
        return {"id": cid, "email": email, "name": name, "user_id": user_id}

    # ------------------------------------------------------------------
    # Subscription lifecycle
    # ------------------------------------------------------------------

    async def create_subscription(self, customer_id: str, tier: str = "pro") -> dict[str, Any]:
        """Create a subscription for the given customer.

        Returns a dict with ``id``, ``customer_id``, ``tier``, ``status``,
        ``current_period_start``, and ``current_period_end``.
        """
        user_id = self._cus_to_user.get(customer_id, customer_id)
        if self._ready and self._scaffold:
            result = await self._scaffold.create_subscription(user_id, tier)
            sub_id = result.stripe_subscription_id or f"sub_{customer_id}"
            self._sub_to_user[sub_id] = user_id
            return {
                "id": sub_id,
                "customer_id": customer_id,
                "tier": result.tier,
                "status": result.status,
                "current_period_start": result.current_period_start.isoformat(),
                "current_period_end": result.current_period_end.isoformat(),
                "cancel_at_period_end": result.cancel_at_period_end,
            }
        sub_id = f"sub_offline_{uuid.uuid4().hex[:12]}"
        self._sub_to_user[sub_id] = user_id
        return {
            "id": sub_id,
            "customer_id": customer_id,
            "tier": tier,
            "status": "active",
        }

    async def cancel_subscription(self, subscription_id: str) -> bool:
        """Cancel a subscription.  Returns ``True`` on success."""
        user_id = self._sub_to_user.get(subscription_id, subscription_id)
        if self._ready and self._scaffold:
            result = await self._scaffold.cancel_subscription(user_id)
            return result.get("status") in ("canceled", "no_subscription")
        return True

    async def change_tier(self, subscription_id: str, new_tier: str) -> bool:
        """Change the tier of a subscription.  Returns ``True`` on success."""
        user_id = self._sub_to_user.get(subscription_id, subscription_id)
        if self._ready and self._scaffold:
            result = await self._scaffold.change_tier(user_id, new_tier)
            return result.get("status") in ("changed", "created")
        return True

    # ------------------------------------------------------------------
    # Entitlement checks
    # ------------------------------------------------------------------

    async def check_entitlement(self, user_id: str, action: str) -> bool:
        """Check whether a user is entitled to perform *action*.

        Common actions: ``"llm_inference"``, ``"rag_pipeline"``,
        ``"swarm"``, ``"domain_router"``, ``"voice_cloning"``.

        Returns ``True`` if the user's tier allows the action.
        """
        if self._ready and self._scaffold:
            result = await self._scaffold.check_entitlement(user_id, feature=action)
            return result.get("allowed", False)
        return True

    # ------------------------------------------------------------------
    # Usage metering
    # ------------------------------------------------------------------

    async def record_usage(self, customer_id: str, usage_type: str, value: float) -> bool:
        """Record usage for a customer.

        *usage_type* can be one of ``"requests"``, ``"tokens"``,
        ``"agents"``, ``"tool_calls"``, or ``"sessions"``.
        """
        user_id = self._cus_to_user.get(customer_id, customer_id)
        if self._ready and self._scaffold:
            params: dict[str, Any] = {"user_id": user_id}
            key = usage_type if usage_type in ("requests", "tokens", "agents") else "requests"
            params[key] = int(value)
            await self._scaffold.record_usage(**params)
            return True
        return True

    async def get_usage_summary(self, customer_id: str) -> dict[str, Any]:
        """Return a usage snapshot for the given customer."""
        user_id = self._cus_to_user.get(customer_id, customer_id)
        if self._ready and self._scaffold:
            return await self._scaffold.report_usage_snapshot(user_id)
        return {"customer_id": customer_id, "usage": {}, "period": "current"}

    # ------------------------------------------------------------------
    # Checkout & portal sessions
    # ------------------------------------------------------------------

    async def create_checkout_session(self, tier: str, customer_id: str | None = None) -> dict[str, Any]:
        """Create a Stripe Checkout session for self-service signup/upgrade.

        Returns a dict with ``url`` and ``session_id``.
        """
        user_id = self._cus_to_user.get(customer_id, customer_id) if customer_id else f"anon_{uuid.uuid4().hex[:8]}"
        if self._ready and self._scaffold:
            result = await self._scaffold.create_checkout_session(
                user_id=user_id,
                tier=tier,
                success_url="http://localhost:8000/billing?success=1",
                cancel_url="http://localhost:8000/billing",
            )
            return {"url": result.get("url", ""), "session_id": result.get("id", "")}
        return {"url": "http://localhost:8000/billing", "session_id": f"cs_offline_{uuid.uuid4().hex[:12]}"}

    async def create_portal_session(self, customer_id: str) -> dict[str, Any]:
        """Create a Stripe Customer Portal session.

        Returns a dict with ``url`` and ``session_id``.
        """
        user_id = self._cus_to_user.get(customer_id, customer_id)
        if self._ready and self._scaffold:
            result = await self._scaffold.create_portal_session(
                user_id=user_id,
                return_url="http://localhost:8000/billing",
            )
            return {"url": result.get("url", ""), "session_id": result.get("id", "")}
        return {"url": "http://localhost:8000/billing", "session_id": f"ps_offline_{uuid.uuid4().hex[:12]}"}

    # ------------------------------------------------------------------
    # Webhook handling
    # ------------------------------------------------------------------

    async def handle_webhook(self, payload: bytes, signature: str) -> dict[str, Any]:
        """Verify and process a Stripe webhook event.

        Returns a dict with ``status`` and ``event_type``.
        """
        if self._ready and self._scaffold:
            return await self._scaffold.handle_webhook(payload, signature)
        return {"status": "ignored", "event_type": "offline"}
