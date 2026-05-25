"""Audit trail API — compliance-ready action log for all Orchestra verticals."""
from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query

from orchestra.code_agent.audit import store


def register_audit_routes(app: FastAPI) -> None:
    store.init_db()

    @app.get("/api/audit/log")
    async def get_audit_log(
        user_id: str = Query(""),
        vertical: str = Query("", description="legal | finance | healthcare | code_agent | auth"),
        action: str = Query(""),
        limit: int = Query(100, ge=1, le=500),
        offset: int = Query(0, ge=0),
        since_days: float = Query(30, description="Look back N days"),
    ):
        """
        Return the tamper-evident audit trail.

        Every AI query, document draft, agentic run, login, and data access
        is logged here with a chained hash for integrity verification.
        """
        import time
        since_ts = time.time() - since_days * 86400
        entries = store.query(
            user_id=user_id,
            vertical=vertical,
            action=action,
            limit=limit,
            offset=offset,
            since_ts=since_ts,
        )
        from dataclasses import asdict
        return {
            "count": len(entries),
            "entries": [asdict(e) for e in entries],
        }

    @app.get("/api/audit/summary")
    async def audit_summary(
        user_id: str = Query(""),
        days: int = Query(30, ge=1, le=365),
    ):
        """Aggregated stats: total actions, failures, token usage, breakdown by vertical and action."""
        return store.summary(user_id=user_id, days=days)

    @app.post("/api/audit/log")
    async def write_audit_entry(body: dict[str, Any]):
        """
        Internal endpoint — log an action from any Orchestra vertical.
        Called by the v1_compat layer, agent runs, and vertical modules.
        """
        required = ("user_id", "action")
        if any(k not in body for k in required):
            raise HTTPException(400, f"Required: {list(required)}")
        entry = store.log(
            user_id=body["user_id"],
            action=body["action"],
            vertical=body.get("vertical", ""),
            resource_id=body.get("resource_id", ""),
            resource_type=body.get("resource_type", ""),
            input_text=body.get("input_text", ""),
            output_text=body.get("output_text", ""),
            model=body.get("model", ""),
            tokens_used=int(body.get("tokens_used", 0)),
            duration_ms=int(body.get("duration_ms", 0)),
            success=bool(body.get("success", True)),
            error=body.get("error", ""),
            ip_address=body.get("ip_address", ""),
        )
        from dataclasses import asdict
        return asdict(entry)
