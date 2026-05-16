"""
openjarvis/server/briefing_routes.py
──────────────────────────────────────
Thin FastAPI router for Enterprise Daily Briefing status and trigger endpoints.

Endpoints:
  GET  /briefing/status    Return recent delivery history for the authenticated customer
  POST /briefing/trigger   Immediately trigger a briefing delivery
"""

from __future__ import annotations

from typing import Optional

try:
    from fastapi import APIRouter, Header, HTTPException, status
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False


def create_briefing_status_router(scheduler=None, auth_fn=None, tier_fn=None):
    """Factory that returns a FastAPI ``APIRouter`` for briefing status/trigger endpoints.

    Args:
        scheduler: An instance of :class:`openjarvis.briefing.BriefingScheduler`.
            When *None* both endpoints return a 503 with a helpful message.
        auth_fn: ``callable(api_key: str) -> Optional[str]`` returning the
            ``customer_id`` for a valid API key.
        tier_fn: ``callable(customer_id: str) -> str`` returning the customer's
            plan tier (e.g. ``"enterprise"``).  Enterprise is required for
            ``/briefing/trigger``.

    Returns:
        A :class:`fastapi.APIRouter` mounted at ``/briefing``.
    """
    if not HAS_FASTAPI:
        raise ImportError("FastAPI required: pip install fastapi uvicorn")

    router = APIRouter(prefix="/briefing", tags=["Briefing"])

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

    def _check_enterprise(customer_id: str) -> None:
        if tier_fn:
            tier = tier_fn(customer_id)
            if tier.lower() != "enterprise":
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        "Daily Briefings require the Enterprise plan ($499/mo). "
                        "Upgrade at openjarvis.com/billing."
                    ),
                )

    def _require_scheduler():
        if scheduler is None:
            raise HTTPException(
                status_code=503,
                detail="Briefing scheduler not configured. Pass a BriefingScheduler to create_briefing_status_router().",
            )

    @router.get("/status")
    async def briefing_status(
        last_n: int = 5,
        authorization: str = Header(...),
    ):
        """Return the recent delivery history for the authenticated customer's briefing."""
        _require_scheduler()

        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        api_key = authorization.removeprefix("Bearer ").strip()
        customer_id = auth_fn(api_key) if auth_fn else api_key
        if auth_fn and not customer_id:
            raise HTTPException(status_code=401, detail="Invalid API key")

        config = scheduler.get_config(customer_id)
        if not config:
            raise HTTPException(status_code=404, detail="Briefing not found")

        from pathlib import Path
        import json

        log_dir = Path("openjarvis/data/briefing_logs") / customer_id
        if not log_dir.exists():
            return {"customer_id": customer_id, "total_deliveries": 0, "deliveries": []}

        logs = sorted(log_dir.glob("*.json"), reverse=True)
        deliveries = []
        for fp in logs[:last_n]:
            try:
                deliveries.append(json.loads(fp.read_text()))
            except Exception:
                pass

        return {
            "customer_id": customer_id,
            "total_deliveries": len(logs),
            "deliveries": deliveries,
        }

    @router.post("/trigger", status_code=status.HTTP_200_OK)
    async def briefing_trigger(authorization: str = Header(...)):
        """Immediately run and deliver the briefing for the authenticated customer."""
        _require_scheduler()

        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        api_key = authorization.removeprefix("Bearer ").strip()
        customer_id = auth_fn(api_key) if auth_fn else api_key
        if auth_fn and not customer_id:
            raise HTTPException(status_code=401, detail="Invalid API key")

        _check_enterprise(customer_id)

        config = scheduler.get_config(customer_id)
        if not config:
            raise HTTPException(status_code=404, detail="Briefing not found")

        try:
            result = await scheduler.trigger_now(customer_id)
            return {
                "success": True,
                "subject": result.subject,
                "has_breaking_news": result.has_breaking_news,
                "breaking_summary": result.breaking_summary,
                "generated_at": result.generated_at,
                "recipients": config.delivery.recipients,
            }
        except KeyError:
            raise HTTPException(status_code=404, detail="Briefing not found")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

    return router
