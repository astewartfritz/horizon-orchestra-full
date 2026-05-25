"""
Notification API routes.

POST /api/notifications/test          send a test email (admin)
POST /api/notifications/digest        send weekly digest to user
POST /api/notifications/compliance-alert  trigger compliance alert email
POST /api/notifications/billing       send billing summary email
GET  /api/notifications               list notification history for user
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Header, HTTPException

from orchestra.code_agent.notifications import email as _em

_log = logging.getLogger("orchestra.notifications")


def _get_user_id(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Authorization")
    from orchestra.code_agent.auth.jwt import JWTManager
    from orchestra.code_agent.settings import settings
    payload = JWTManager(secret=settings.jwt_secret).verify(authorization[7:])
    if not payload:
        raise HTTPException(401, "Invalid token")
    return payload["sub"]


def register_notification_routes(app: FastAPI) -> None:
    _em.init_db()

    @app.get("/api/notifications")
    async def list_notifs(
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        return _em.list_notifications(user_id)

    @app.post("/api/notifications/test")
    async def send_test(
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        to = (body.get("email") or "").strip()
        if not to:
            raise HTTPException(400, "email is required")
        n = _em.send_email(
            to=to,
            subject="Orchestra — test notification",
            html="<p>This is a test notification from Orchestra. If you received this, email sending is working correctly.</p>",
            user_id=user_id,
            notification_type="general",
        )
        return {"id": n.id, "status": n.status, "error": n.error}

    @app.post("/api/notifications/digest")
    async def send_digest(
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        to = (body.get("email") or "").strip()
        if not to:
            raise HTTPException(400, "email is required")
        from orchestra.code_agent.history import conversation_stats
        stats = conversation_stats(user_id)
        n = _em.send_weekly_digest(
            to=to,
            user_name=body.get("name", ""),
            conversations=stats["total_conversations"],
            tokens=stats["total_tokens"],
            top_activity=body.get("top_activity", []),
            user_id=user_id,
        )
        return {"id": n.id, "status": n.status}

    @app.post("/api/notifications/compliance-alert")
    async def send_compliance_alert(
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        to = (body.get("email") or "").strip()
        title = body.get("title", "Compliance alert")
        msg = body.get("message", "")
        severity = body.get("severity", "warning")
        if not to:
            raise HTTPException(400, "email is required")
        n = _em.send_compliance_alert(
            to=to, alert_title=title, alert_body=msg, severity=severity, user_id=user_id,
        )
        return {"id": n.id, "status": n.status}

    @app.post("/api/notifications/billing")
    async def send_billing(
        body: dict,
        authorization: str | None = Header(default=None),
    ):
        user_id = _get_user_id(authorization)
        to = (body.get("email") or "").strip()
        if not to:
            raise HTTPException(400, "email is required")
        n = _em.send_billing_summary(
            to=to,
            period=body.get("period", ""),
            plan=body.get("plan", ""),
            amount=body.get("amount", ""),
            next_billing=body.get("next_billing", ""),
            usage_items=body.get("usage_items", []),
            user_id=user_id,
        )
        return {"id": n.id, "status": n.status}
