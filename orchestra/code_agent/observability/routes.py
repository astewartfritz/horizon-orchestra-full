"""Log viewer API routes."""
from __future__ import annotations

import platform
import sys
import time
from typing import Any

from fastapi import FastAPI

from .store import add_event, clear_events, get_stats, list_events

_START_TIME = time.time()


def register_log_routes(app: FastAPI) -> None:

    @app.get("/api/logs")
    async def get_logs(
        level: str = "",
        source: str = "",
        search: str = "",
        limit: int = 200,
        offset: int = 0,
    ):
        events = list_events(
            level=level, source=source, search=search,
            limit=min(limit, 500), offset=offset,
        )
        return {"count": len(events), "events": events}

    @app.get("/api/logs/stats")
    async def log_stats():
        return get_stats()

    @app.delete("/api/logs")
    async def delete_logs():
        n = clear_events()
        return {"deleted": n}

    @app.post("/api/logs/ingest")
    async def ingest_log(body: dict[str, Any]):
        """Manual log injection — used by verticals and the UI for client-side errors."""
        add_event(
            level=body.get("level", "INFO"),
            source=body.get("source", "client"),
            message=body.get("message", ""),
            details=body.get("details"),
            request_id=body.get("request_id", ""),
        )
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        """Production health check — returns uptime, Python version, and recent error rate."""
        stats = get_stats()
        uptime_s = int(time.time() - _START_TIME)
        return {
            "status": "ok",
            "uptime_seconds": uptime_s,
            "uptime_human": _fmt_uptime(uptime_s),
            "python": sys.version.split()[0],
            "platform": platform.system(),
            "errors_1h": stats["errors_1h"],
            "errors_24h": stats["errors_24h"],
            "total_log_events": stats["total"],
        }


def _fmt_uptime(s: int) -> str:
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s//60}m {s%60}s"
    h = s // 3600
    return f"{h}h {(s%3600)//60}m"
