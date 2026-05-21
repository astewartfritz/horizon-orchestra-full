"""FastAPI routes for Orchestra billing (Stripe)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

log = logging.getLogger("orchestra.billing")

UPGRADE_HINT = {
    "error": "subscription_required",
    "message": "This feature requires an Orchestra Pro subscription ($50/month).",
    "upgrade_url": "/billing",
}


def require_pro(local_id: str) -> None:
    """Raise 402 if the customer does not have an active Pro subscription."""
    from orchestra.code_agent.billing.store import SubscriptionStore
    if not local_id:
        raise HTTPException(status_code=402, detail=UPGRADE_HINT)
    if not SubscriptionStore.get().is_active(local_id):
        raise HTTPException(status_code=402, detail=UPGRADE_HINT)


def register_billing_routes(app: Any) -> None:
    from orchestra.code_agent.billing.client import StripeClient
    from orchestra.code_agent.billing.store import SubscriptionStore
    from orchestra.code_agent.ui.billing_page import BILLING_PAGE_HTML

    stripe_client = StripeClient.get()
    store = SubscriptionStore.get()
    router = APIRouter(prefix="/api/billing")

    # ── Billing page ─────────────────────────────────────────────────────────

    @app.get("/billing", response_class=HTMLResponse)
    async def billing_page(success: int = 0, canceled: int = 0):
        return BILLING_PAGE_HTML

    @app.get("/billing/success", response_class=HTMLResponse)
    async def billing_success():
        return RedirectResponse(url="/billing?success=1")

    # ── Status ────────────────────────────────────────────────────────────────

    @router.get("/status")
    async def billing_status(request: Request):
        local_id = request.headers.get("X-Customer-Id", "")
        if not local_id:
            return {"plan": "free", "status": "none", "active": False,
                    "stripe_configured": stripe_client.configured,
                    "publishable_key": stripe_client.publishable_key}
        info = store.subscription_info(local_id)
        info["stripe_configured"] = stripe_client.configured
        info["publishable_key"] = stripe_client.publishable_key
        return info

    # ── Checkout ──────────────────────────────────────────────────────────────

    @router.post("/checkout")
    async def create_checkout(request: Request, body: dict[str, Any] = {}):
        if not stripe_client.configured:
            raise HTTPException(
                status_code=503,
                detail="Stripe not configured. Set STRIPE_SECRET_KEY.",
            )
        local_id = request.headers.get("X-Customer-Id", "") or body.get("local_id", "")
        if not local_id:
            raise HTTPException(status_code=400, detail="X-Customer-Id header required")

        origin = request.headers.get("origin", "http://localhost:8000")
        email = body.get("email", "")

        try:
            url = stripe_client.create_checkout_session(
                local_id=local_id,
                email=email,
                success_url=f"{origin}/billing?success=1",
                cancel_url=f"{origin}/billing",
            )
            return {"url": url}
        except Exception as exc:
            log.error("Checkout error: %s", exc)
            raise HTTPException(status_code=502, detail=str(exc))

    # ── Customer Portal ───────────────────────────────────────────────────────

    @router.post("/portal")
    async def customer_portal(request: Request, body: dict[str, Any] = {}):
        if not stripe_client.configured:
            raise HTTPException(status_code=503, detail="Stripe not configured.")
        local_id = request.headers.get("X-Customer-Id", "") or body.get("local_id", "")
        if not local_id:
            raise HTTPException(status_code=400, detail="X-Customer-Id header required")

        origin = request.headers.get("origin", "http://localhost:8000")
        try:
            url = stripe_client.create_portal_session(
                local_id=local_id,
                return_url=f"{origin}/billing",
            )
            return {"url": url}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc))

    # ── Webhook ───────────────────────────────────────────────────────────────

    @router.post("/webhook")
    async def stripe_webhook(request: Request):
        payload = await request.body()
        sig = request.headers.get("stripe-signature", "")

        if not stripe_client._webhook_secret:
            # Dev mode: skip signature verification
            import json
            event = json.loads(payload)
        else:
            try:
                event = stripe_client.construct_event(payload, sig)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Webhook error: {exc}")

        try:
            stripe_client.handle_webhook_event(event)
        except Exception as exc:
            log.error("Webhook handler error: %s", exc)

        return {"received": True}

    app.include_router(router)
