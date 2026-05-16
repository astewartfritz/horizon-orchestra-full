from __future__ import annotations

from fastapi import FastAPI, HTTPException
from code_agent.session import SessionManager


def register_session_routes(app: FastAPI, sessions: SessionManager) -> None:
    @app.get("/api/sessions")
    async def list_sessions(q: str = ""):
        items = sessions.list_sessions()
        if not items:
            return '<div style="color:#8b949e;font-size:13px;padding:8px">No sessions yet</div>'
        import html as _html
        parts = []
        for s in items:
            task_preview = _html.escape(s["task"][:60])
            last_preview = _html.escape(s.get("last_response", "")[:80])
            created = s.get("created_at", "")[:10]
            finished = s.get("finished", False)
            msg_count = s.get("message_count", 0)
            status = "done" if finished else "in-progress"
            preview_html = f'<div class="preview">{last_preview}</div>' if last_preview else ''
            parts.append(
                f'<div class="session-item {status}" data-session="{s["id"]}" onclick="loadSession(\'{s["id"]}\')">'
                f'<button class="session-del" onclick="event.stopPropagation();deleteSession(\'{s["id"]}\')" title="Delete">&#x2716;</button>'
                f'<div class="task">{task_preview}</div>'
                f'{preview_html}'
                f'<div class="date">{created} &middot; {msg_count} msgs</div>'
                f'</div>'
            )
        return "".join(parts)

    @app.delete("/api/sessions/{sid}")
    async def delete_session(sid: str):
        from code_agent.session import Session
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
        from datetime import datetime as _dt
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
        from fastapi.responses import PlainTextResponse, Response
        if fmt == "md":
            return PlainTextResponse(body, media_type="text/markdown", headers={"Content-Disposition": f"attachment; filename=session-{sid}.md"})
        else:
            return PlainTextResponse(body)

    @app.get("/api/sessions/{sid}/messages")
    async def get_session_messages(sid: str):
        session = sessions.load(sid)
        if not session:
            return "<div style='color:#8b949e;padding:16px'>Session not found</div>"
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
            return "<div style='color:#8b949e;padding:16px'>No messages</div>"
        return "".join(parts)
