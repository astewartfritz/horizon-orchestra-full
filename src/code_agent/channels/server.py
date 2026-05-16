"""Webhook endpoints for each channel. Mounted on the FastAPI Gateway."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request

from code_agent.channels.manager import ChannelType
from code_agent.channels.ingress import MessageRouter


def register_channel_webhooks(app: FastAPI, router: MessageRouter) -> None:
    """Register webhook endpoints for Slack, Telegram, Discord, WhatsApp."""

    logger = logging.getLogger("orchestra.webhooks")

    # ── Slack ────────────────────────────────────────────────
    @app.post("/channels/slack")
    async def slack_webhook(request: Request):
        body = await _parse_body(request)
        result = await router.handle_webhook(ChannelType.SLACK, body)
        if result["status"] == "ignored":
            return {"ok": True}  # Slack requires 200 for URL verification
        return result

    @app.get("/channels/slack")
    async def slack_verify(request: Request):
        # Slack URL verification challenge
        body = await _parse_body(request)
        challenge = body.get("challenge", "")
        if challenge:
            return {"challenge": challenge}
        return {"ok": True}

    # ── Telegram ─────────────────────────────────────────────
    @app.post("/channels/telegram")
    async def telegram_webhook(request: Request):
        body = await _parse_body(request)
        result = await router.handle_webhook(ChannelType.TELEGRAM, body)
        return result

    # ── Discord ──────────────────────────────────────────────
    @app.post("/channels/discord")
    async def discord_webhook(request: Request):
        body = await _parse_body(request)
        # Handle Discord interaction ping
        if body.get("type") == 1:
            return {"type": 1}
        result = await router.handle_webhook(ChannelType.DISCORD, body)
        return result

    # ── WhatsApp ─────────────────────────────────────────────
    @app.post("/channels/whatsapp")
    async def whatsapp_webhook(request: Request):
        body = await _parse_body(request)
        result = await router.handle_webhook(ChannelType.WHATSAPP, body)
        return result

    # ── WhatsApp verification ────────────────────────────────
    @app.get("/channels/whatsapp")
    async def whatsapp_verify(request: Request):
        mode = request.query_params.get("hub.mode", "")
        token = request.query_params.get("hub.verify_token", "")
        challenge = request.query_params.get("hub.challenge", "")
        verify_token = "orchestra_verify_2026"
        if mode == "subscribe" and token == verify_token:
            return int(challenge)
        raise HTTPException(status_code=403, detail="Verification failed")

    # ── Generic webhook for custom integrations ──────────────
    @app.post("/channels/webhook/{source}")
    async def generic_webhook(source: str, request: Request):
        body = await _parse_body(request)
        logger.info("Webhook from %s: %s", source, str(body)[:200])
        return {"status": "received", "source": source}


async def _parse_body(request: Request) -> dict[str, Any]:
    try:
        return await request.json()
    except Exception:
        try:
            text = await request.body()
            import json
            return json.loads(text) if text else {}
        except Exception:
            return {}
