"""TypeScript channels bridge — routes webhook requests to the TypeScript channels server.

Orchestra runs the TypeScript channels server on port 4500 for
multi-channel message ingestion (Slack, Telegram, WhatsApp, Discord, iMessage, Email).
This bridge registers the webhook routes on the main Orchestra FastAPI server
and proxies them to the TypeScript backend.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("orchestra.channels_bridge")

_CHANNELS_TS_URL = "http://127.0.0.1:4500"
_TS_AVAILABLE = False


async def _check_ts_server() -> bool:
    global _TS_AVAILABLE
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(f"{_CHANNELS_TS_URL}/health")
            _TS_AVAILABLE = r.status_code == 200
            return _TS_AVAILABLE
    except Exception:
        _TS_AVAILABLE = False
        return False


async def proxy_to_ts(channel: str, body: dict[str, Any]) -> dict[str, Any]:
    """Proxy a webhook request to the TypeScript channels server."""
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{_CHANNELS_TS_URL}/webhook/{channel}",
                json=body,
                headers={"Content-Type": "application/json"},
            )
            if r.status_code == 200:
                return r.json()
            return {"status": "error", "detail": r.text[:200]}
    except httpx.ConnectError:
        return {"status": "ts_server_unavailable", "detail": "TypeScript channels server not running on port 4500"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


def register_channel_bridge_routes(app: Any) -> None:
    """Register webhook routes that proxy to the TypeScript channels server."""

    @app.get("/channels/health")
    async def channels_health():
        ts_ok = await _check_ts_server()
        return {
            "ts_server": ts_ok,
            "ts_url": _CHANNELS_TS_URL,
            "message": "TypeScript channels server is running" if ts_ok else "TypeScript channels server not running — start with: cd channels/ts && npm run dev",
        }

    @app.post("/channels/{channel}")
    async def channel_webhook(channel: str):
        body_raw = await __import__("json").dumps({})
        body_raw = await __import__("fastapi").requests.Request.body()
        try:
            body = json.loads(body_raw) if body_raw else {}
        except Exception:
            body = {}
        return await proxy_to_ts(channel, body)

    @app.get("/channels/{channel}")
    async def channel_webhook_get(channel: str):
        return await proxy_to_ts(channel, {})
