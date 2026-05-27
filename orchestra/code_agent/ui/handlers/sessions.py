from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from orchestra.code_agent.session import Session, SessionManager


def register_session_routes(app: FastAPI, sessions: SessionManager) -> None:

    @app.get("/api/sessions")
    async def list_sessions(request: Request, q: str = ""):
        items = sessions.list_sessions()

        # HTMX sets HX-Request: true; return HTML fragment for it.
        # All other clients (REST, test) get JSON.
        if request.headers.get("hx-request") == "true":
            if not items:
                return HTMLResponse('<div style="color:#8b949e;font-size:13px;padding:8px">No sessions yet</div>')
            import html as _html
            parts = []
            for s in items:
                headline = _html.escape(s["task"][:72])
                status = "done" if s.get("finished", False) else "in-progress"
                created = (s.get("created_at") or "")[:10]
                msg_count = s.get("message_count", 0)
                meta_parts = []
                if created:
                    meta_parts.append(created)
                if msg_count:
                    meta_parts.append(f"{msg_count} msg{'s' if msg_count != 1 else ''}")
                meta_html = (
                    f'<div class="session-meta">{" &middot; ".join(meta_parts)}</div>'
                    if meta_parts else ""
                )
                parts.append(
                    f'<div class="session-item {status}" data-session="{s["id"]}" onclick="loadSession(\'{s["id"]}\')">'
                    f'<button class="session-del" onclick="event.stopPropagation();deleteSession(\'{s["id"]}\')" title="Delete">&#x2716;</button>'
                    f'<div class="task">{headline}</div>'
                    f'{meta_html}'
                    f'</div>'
                )
            return HTMLResponse("".join(parts))

        return JSONResponse(items)

    @app.post("/api/sessions")
    async def create_session(request: Request):
        try:
            body = await request.json()
        except Exception:
            body = {}

        now = datetime.now(timezone.utc).isoformat()
        session = Session(
            id=uuid.uuid4().hex[:12],
            task=body.get("name") or body.get("task") or "New Session",
            created_at=now,
            updated_at=now,
        )
        sessions.save(session)
        return JSONResponse(
            {"id": session.id, "task": session.task, "created_at": session.created_at},
            status_code=201,
        )

    @app.get("/api/sessions/{sid}")
    async def get_session(sid: str):
        session = sessions.load(sid)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse(session.to_dict())

    @app.delete("/api/sessions/{sid}")
    async def delete_session(sid: str):
        session = sessions.load(sid)
        if session:
            import os as _os
            try:
                _os.remove(str(sessions.path / f"{sid}.json"))
            except Exception:
                pass
            return {"deleted": True}
        raise HTTPException(status_code=404, detail="Session not found")

    @app.get("/api/sessions/{sid}/export")
    async def export_session(sid: str, fmt: str = "md"):
        session = sessions.load(sid)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        lines = [f"# Orchestra Session: {session.task}", f"Date: {session.created_at}", f"Turns: {len(session.messages) // 2}", ""]
        for m in session.messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if not content:
                continue
            label = {"user": "**You**", "assistant": "**Agent**", "system": "**System**", "tool": "**Tool**"}.get(role, role)
            lines.append(f"### {label}")
            lines.append(content[:2000])
            lines.append("")
        body = "\n".join(lines)
        from fastapi.responses import PlainTextResponse
        if fmt == "md":
            return PlainTextResponse(body, media_type="text/markdown", headers={"Content-Disposition": f"attachment; filename=session-{sid}.md"})
        return PlainTextResponse(body)

    @app.get("/api/sessions/{sid}/messages")
    async def get_session_messages(sid: str):
        session = sessions.load(sid)
        if not session:
            return HTMLResponse("<div style='color:#8b949e;padding:16px'>Session not found</div>")
        import html as _html
        parts = []
        for m in session.messages:
            role = m.get("role", "unknown")
            content = m.get("content", "")
            if not content:
                continue
            label = {"user": "You", "assistant": "Agent", "tool": "Tool", "system": "System"}.get(role, role)
            escaped = _html.escape(content[:2000])
            if role == "system":
                parts.append(f'<div class="msg system"><div class="msg-label">{label}</div><div class="msg-content" style="font-size:12px;color:var(--text-secondary)">{escaped}</div></div>')
            elif role == "user":
                parts.append(f'<div class="msg user"><div class="msg-label">{label}</div><div style="margin-top:2px">{escaped}</div></div>')
            else:
                parts.append(f'<div class="msg assistant"><div class="msg-label">{label}</div><div class="msg-content">{escaped}</div></div>')
        if not parts:
            return HTMLResponse("<div style='color:#8b949e;padding:16px'>No messages</div>")
        return HTMLResponse("".join(parts))
