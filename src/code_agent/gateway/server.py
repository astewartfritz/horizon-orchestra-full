"""FastAPI-based Gateway server. Exposes REST endpoints for all channels."""
from __future__ import annotations

import os
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from code_agent.channels.manager import ChannelType
from code_agent.gateway.runtime import Gateway, GatewayEvent, AgentRuntime
from code_agent.gateway.webhooks import WebhookManager
from code_agent.gateway.adapters import get_adapter, ADAPTER_REGISTRY


def create_gateway_app() -> FastAPI:
    """Create the FastAPI Gateway application."""
    app = FastAPI(title="Orchestra Gateway")
    gateway = Gateway()
    logger = logging.getLogger("orchestra.gateway")

    # ── Health ────────────────────────────────────────────────
    @app.get("/health")
    async def health():
        return {"status": "ok", "service": "gateway", "sessions": len(gateway._sessions)}

    # ── Chat (Web/CLI) ────────────────────────────────────────
    @app.post("/api/chat")
    async def chat(body: dict[str, Any]):
        event = GatewayEvent(
            content=body.get("task", body.get("content", "")),
            channel=ChannelType.WEB,
            sender=body.get("sender", "user"),
            metadata=body,
        )
        try:
            result = await gateway.handle_event(event, api_key=body.get("api_key"))
            return {"response": result, "session_id": event.session_id}
        except PermissionError:
            raise HTTPException(status_code=401, detail="Authentication required")

    # ── Webhooks ──────────────────────────────────────────────
    @app.post("/webhook/{source}")
    async def webhook(source: str, request: Request):
        payload = await request.json()
        signature = request.headers.get("X-Hub-Signature-256", "")
        body_bytes = await request.body()

        if not gateway.webhooks.verify(source, body_bytes, signature):
            raise HTTPException(status_code=401, detail="Invalid signature")

        result = await gateway.webhooks.handle(source, payload)
        return {"status": "received", "detail": result}

    # ── Channel adapters ──────────────────────────────────────
    @app.post("/channels/{channel}/receive")
    async def channel_receive(channel: str, body: dict[str, Any]):
        try:
            ct = ChannelType(channel)
            adapter = get_adapter(ct)
            msg = await adapter.receive(body)
            if not msg:
                raise HTTPException(status_code=400, detail="Unrecognized message format")
            event = GatewayEvent(
                content=msg.content,
                channel=ct,
                sender=msg.sender,
                metadata=msg.metadata,
            )
            result = await gateway.handle_event(event)
            return {"response": result}
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown channel: {channel}")

    # ── Admin ─────────────────────────────────────────────────
    @app.get("/admin/sessions")
    async def list_sessions():
        return {"sessions": gateway.list_sessions()}

    @app.get("/admin/sessions/{session_id}")
    async def get_session(session_id: str):
        session = gateway.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404)
        return session

    @app.post("/admin/api-keys")
    async def create_api_key(body: dict[str, str]):
        import uuid
        key = str(uuid.uuid4())
        gateway.register_api_key(key, body.get("session_id", "default"))
        return {"api_key": key}

    return app
