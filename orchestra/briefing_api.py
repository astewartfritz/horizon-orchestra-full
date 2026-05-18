"""
orchestra/briefing_api.py
──────────────────────────
FastAPI router for Enterprise Daily Briefing endpoints.
Mounted into arch_e.py under /enterprise/briefings.

Endpoints:
  POST   /enterprise/briefings                    Create briefing
  GET    /enterprise/briefings/{customer_id}       Get config
  PATCH  /enterprise/briefings/{customer_id}       Update config
  DELETE /enterprise/briefings/{customer_id}       Delete briefing
  POST   /enterprise/briefings/{customer_id}/topics         Add topic
  DELETE /enterprise/briefings/{customer_id}/topics/{tid}   Remove topic
  POST   /enterprise/briefings/{customer_id}/trigger        Trigger now
  GET    /enterprise/briefings/{customer_id}/status         Delivery history

All endpoints require:
  - Authorization: Bearer <api_key>
  - Customer must be on Enterprise tier ($499/mo)
"""

from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone

try:
    from fastapi import APIRouter, HTTPException, Depends, Header, status
    from pydantic import BaseModel, EmailStr, field_validator
    HAS_FASTAPI = True
except ImportError:
    HAS_FASTAPI = False

from .briefing_config import (
    BriefingConfig,
    BriefingTopic,
    DeliveryConfig,
    create_default_config,
)


# ──────────────────────────────────────────────
# Request / response models
# ──────────────────────────────────────────────

if HAS_FASTAPI:
    class TopicRequest(BaseModel):
        name: str
        queries: list[str]
        breaking_keywords: list[str] = []

    class CreateBriefingRequest(BaseModel):
        customer_id: str
        briefing_name: str = "Daily Intelligence Briefing"
        recipients: list[str]
        send_hour_utc: int = 13
        topics: list[TopicRequest] = []

        @field_validator("send_hour_utc")
        @classmethod
        def valid_hour(cls, v):
            if not 0 <= v <= 23:
                raise ValueError("send_hour_utc must be 0-23")
            return v

    class UpdateBriefingRequest(BaseModel):
        briefing_name: Optional[str] = None
        recipients: Optional[list[str]] = None
        send_hour_utc: Optional[int] = None
        enabled: Optional[bool] = None

    class BriefingResponse(BaseModel):
        success: bool
        config_id: str
        customer_id: str
        briefing_name: str
        topics: int
        recipients: list[str]
        schedule: str
        enabled: bool
        message: str = ""

    class TopicResponse(BaseModel):
        success: bool
        topic_id: str
        topic_name: str
        total_topics: int


# ──────────────────────────────────────────────
# Router factory
# ──────────────────────────────────────────────

def create_briefing_router(scheduler, auth_fn=None, tier_fn=None):
    """
    Factory: returns a FastAPI APIRouter wired to the BriefingScheduler.

    Args:
        scheduler: BriefingScheduler instance
        auth_fn:   callable(api_key) -> customer_id  (raises HTTPException on failure)
        tier_fn:   callable(customer_id) -> str tier
    """
    if not HAS_FASTAPI:
        raise ImportError("FastAPI required: pip install fastapi uvicorn")

    router = APIRouter(prefix="/enterprise/briefings", tags=["Enterprise Briefings"])

    def _get_customer(authorization: str = Header(...)) -> str:
        if not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Invalid Authorization header")
        api_key = authorization.removeprefix("Bearer ").strip()
        if auth_fn:
            customer_id = auth_fn(api_key)
            if not customer_id:
                raise HTTPException(status_code=401, detail="Invalid API key")
            return customer_id
        # Dev mode: accept any key, use as customer_id
        return api_key

    def _check_enterprise(customer_id: str) -> None:
        if tier_fn:
            tier = tier_fn(customer_id)
            if tier.lower() != "enterprise":
                raise HTTPException(
                    status_code=status.HTTP_402_PAYMENT_REQUIRED,
                    detail=(
                        f"Daily Briefings require the Enterprise plan ($499/mo). "
                        f"Upgrade at horizon-orchestra.com/billing."
                    ),
                )

    # ── Create ────────────────────────────────────────────────────────────────

    @router.post("", response_model=BriefingResponse, status_code=201)
    async def create_briefing(
        body: CreateBriefingRequest,
        customer_id: str = Depends(_get_customer),
    ):
        _check_enterprise(customer_id)
        config = create_default_config(
            customer_id=customer_id,
            recipients=body.recipients,
            briefing_name=body.briefing_name,
            send_hour_utc=body.send_hour_utc,
        )
        for t in body.topics:
            topic = BriefingTopic.create(t.name, t.queries, t.breaking_keywords)
            config.add_topic(topic)

        tier = tier_fn(customer_id) if tier_fn else "enterprise"
        scheduler.add_config(config, tier)

        return BriefingResponse(
            success=True,
            config_id=config.id,
            customer_id=customer_id,
            briefing_name=config.briefing_name,
            topics=len(config.topics),
            recipients=config.delivery.recipients,
            schedule=config.delivery.cron_expression,
            enabled=config.enabled,
            message=(
                f"Briefing '{config.briefing_name}' created. "
                f"Daily delivery at {body.send_hour_utc}:00 UTC."
            ),
        )

    # ── Get ───────────────────────────────────────────────────────────────────

    @router.get("/{customer_id}")
    async def get_briefing(
        customer_id: str,
        _auth: str = Depends(_get_customer),
    ):
        config = scheduler.get_config(customer_id)
        if not config:
            raise HTTPException(status_code=404, detail="Briefing not found")
        return config.to_dict()

    # ── Update ────────────────────────────────────────────────────────────────

    @router.patch("/{customer_id}")
    async def update_briefing(
        customer_id: str,
        body: UpdateBriefingRequest,
        _auth: str = Depends(_get_customer),
    ):
        _check_enterprise(customer_id)
        config = scheduler.get_config(customer_id)
        if not config:
            raise HTTPException(status_code=404, detail="Briefing not found")

        if body.briefing_name is not None:
            config.briefing_name = body.briefing_name
        if body.recipients is not None:
            config.delivery.recipients = body.recipients
        if body.send_hour_utc is not None:
            config.delivery.send_hour_utc = body.send_hour_utc
            config.delivery.cron_expression = f"0 {body.send_hour_utc} * * *"
        if body.enabled is not None:
            config.enabled = body.enabled

        tier = tier_fn(customer_id) if tier_fn else "enterprise"
        scheduler.update_config(config, tier)
        return {"success": True, "updated": config.to_dict()}

    # ── Delete ────────────────────────────────────────────────────────────────

    @router.delete("/{customer_id}")
    async def delete_briefing(
        customer_id: str,
        _auth: str = Depends(_get_customer),
    ):
        removed = scheduler.remove_config(customer_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Briefing not found")
        return {"success": True, "deleted": customer_id}

    # ── Add topic ─────────────────────────────────────────────────────────────

    @router.post("/{customer_id}/topics", response_model=TopicResponse)
    async def add_topic(
        customer_id: str,
        body: TopicRequest,
        _auth: str = Depends(_get_customer),
    ):
        _check_enterprise(customer_id)
        config = scheduler.get_config(customer_id)
        if not config:
            raise HTTPException(status_code=404, detail="Briefing not found")

        topic = BriefingTopic.create(body.name, body.queries, body.breaking_keywords)
        config.add_topic(topic)
        config.save()
        return TopicResponse(
            success=True,
            topic_id=topic.id,
            topic_name=topic.name,
            total_topics=len(config.topics),
        )

    # ── Remove topic ──────────────────────────────────────────────────────────

    @router.delete("/{customer_id}/topics/{topic_id}")
    async def remove_topic(
        customer_id: str,
        topic_id: str,
        _auth: str = Depends(_get_customer),
    ):
        config = scheduler.get_config(customer_id)
        if not config:
            raise HTTPException(status_code=404, detail="Briefing not found")
        removed = config.remove_topic(topic_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Topic not found")
        config.save()
        return {"success": True, "removed_topic_id": topic_id}

    # ── Trigger now ───────────────────────────────────────────────────────────

    @router.post("/{customer_id}/trigger")
    async def trigger_now(
        customer_id: str,
        _auth: str = Depends(_get_customer),
    ):
        _check_enterprise(customer_id)
        try:
            result = await scheduler.trigger_now(customer_id)
            return {
                "success": True,
                "subject": result.subject,
                "has_breaking_news": result.has_breaking_news,
                "breaking_summary": result.breaking_summary,
                "generated_at": result.generated_at,
            }
        except KeyError:
            raise HTTPException(status_code=404, detail="Briefing not found")

    # ── Status ────────────────────────────────────────────────────────────────

    @router.get("/{customer_id}/status")
    async def status(
        customer_id: str,
        last_n: int = 5,
        _auth: str = Depends(_get_customer),
    ):
        from pathlib import Path
        import json

        log_dir = Path("orchestra/data/briefing_logs") / customer_id
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

    return router
