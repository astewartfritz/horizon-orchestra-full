"""
openjarvis/server/billing_routes.py
─────────────────────────────────────
Thin FastAPI router for billing endpoints.

Endpoints:
  GET  /billing/usage    Return current usage snapshot for the authenticated customer
  POST /billing/webhook  Stripe webhook receiver (raw body, Stripe-Signature header)
"""

from __future__ import annotations

from typing import Optional

try:
    from fastapi import APIRouter, Header, HTTPException, Request, status
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def create_billing_router(billing_manager=None, usage_tracker=None, auth_fn=None):
    """Factory that returns a FastAPI ``APIRouter`` for billing endpoints.

    Args:
        billing_manager: An instance of :class:`openjarvis.billing.BillingManager`
            (or ``NullBillingManager``).  When *None* a null implementation is
            used so the router is still mountable without Stripe configured.
        usage_tracker: An instance of :class:`openjarvis.billing.UsageTracker`
            (or ``NullUsageTracker``).
        auth_fn: ``callable(api_key: str) -> Optional[str]`` returning the
            ``customer_id`` for a valid API key, or ``None`` to reject.

    Returns:
        A :class:`fastapi.APIRouter` mounted at ``/billing``.
    """
    if not HAS_FASTAPI:
        raise ImportError("FastAPI required: pip install fastapi uvicorn")

    try:
        from openjarvis.billing import NullBillingManager, NullUsageTracker
    except ImportError:
        NullBillingManager = None
        NullUsageTracker = None

    if billing_manager is None and NullBillingManager is not None:
        billing_manager = NullBillingManager()
    if usage_tracker is None and NullUsageTracker is not None:
        usage_tracker = NullUsageTracker()

    router = APIRouter(prefix="/billing", tags=["Billing"])

    def _get_customer(authorization: str = Header(...)) -> str:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        api_key = authorization.removeprefix("Bearer ").strip()
        if auth_fn:
            customer_id = auth_fn(api_key)
            if not customer_id:
                raise HTTPException(status_code=401, detail="Invalid API key")
            return customer_id
        return api_key

    @router.get("/usage")
    async def get_usage(customer_id: str = None, authorization: str = Header(...)):
        """Return the current usage snapshot for the authenticated customer."""
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        api_key = authorization.removeprefix("Bearer ").strip()
        resolved_id = customer_id
        if auth_fn and not resolved_id:
            resolved_id = auth_fn(api_key)
            if not resolved_id:
                raise HTTPException(status_code=401, detail="Invalid API key")
        if not resolved_id:
            resolved_id = api_key

        if usage_tracker is None:
            return {"customer_id": resolved_id, "usage": {}, "message": "Usage tracking not configured"}

        try:
            snapshot = await usage_tracker.get_snapshot(resolved_id)
            if hasattr(snapshot, "to_dict"):
                return snapshot.to_dict()
            return {"customer_id": resolved_id, "usage": snapshot}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    @router.post("/webhook", status_code=status.HTTP_200_OK)
    async def stripe_webhook(
        request: Request,
        stripe_signature: Optional[str] = Header(None, alias="Stripe-Signature"),
    ):
        """Receive and process Stripe webhook events."""
        raw_body = await request.body()

        if billing_manager is None:
            return {"received": True, "processed": False, "reason": "billing not configured"}

        try:
            if hasattr(billing_manager, "handle_webhook"):
                result = await billing_manager.handle_webhook(
                    payload=raw_body,
                    signature=stripe_signature or "",
                )
                if hasattr(result, "to_dict"):
                    return result.to_dict()
                return {"received": True, "result": result}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Webhook processing failed: {exc}")

        return {"received": True}

    return router
