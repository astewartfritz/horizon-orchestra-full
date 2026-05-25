from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from orchestra.code_agent.session import SessionManager


def register_memory_timeline_routes(app: FastAPI, sessions: SessionManager) -> None:

    @app.get("/api/memory/timeline")
    async def memory_timeline(
        request: Request,
        q: str = Query("", description="Search query to filter sessions"),
        limit: int = Query(50, ge=1, le=500),
    ):
        items = sessions.list_sessions()
        if q:
            ql = q.lower()
            items = [
                s for s in items
                if ql in s.get("task", "").lower()
                or ql in s.get("last_response", "").lower()
            ]
        items = items[:limit]

        if request.headers.get("hx-request") == "true":
            if not items:
                return '<div style="color:#8b949e;font-size:13px;padding:16px;text-align:center">No past sessions found</div>'
            import html as _html
            parts = ['<div class="timeline">']
            for s in items:
                headline = _html.escape(s.get("task", "Untitled")[:80])
                snippet = _html.escape((s.get("last_response") or "")[:200])
                created = (s.get("created_at") or "")[:19].replace("T", " ")
                msg_count = s.get("message_count", 0)
                sid = _html.escape(s.get("id", ""))
                status = "done" if s.get("finished", False) else "in-progress"
                parts.append(
                    f'<div class="timeline-item {status}" onclick="loadSession(\'{sid}\')">'
                    f'<div class="timeline-headline">{headline}</div>'
                    f'<div class="timeline-snippet">{snippet}</div>'
                    f'<div class="timeline-meta">{created} &middot; {msg_count} msg{"s" if msg_count != 1 else ""}</div>'
                    f'</div>'
                )
            parts.append('</div>')
            return "".join(parts)

        return JSONResponse(items)

    @app.get("/api/memory/recall")
    async def memory_recall(q: str = Query("", description="What to recall")):
        items = sessions.list_sessions()
        if not q:
            raise HTTPException(status_code=400, detail="Query param 'q' is required")

        ql = q.lower()
        results = []
        for s in items:
            sid = s.get("id", "")
            session = sessions.load(sid)
            if not session:
                continue
            for m in session.messages:
                content = (m.get("content") or "")
                if ql in content.lower():
                    results.append({
                        "session_id": sid,
                        "session_task": s.get("task", ""),
                        "created_at": s.get("created_at", ""),
                        "role": m.get("role", ""),
                        "snippet": content[:500],
                    })
                    if len(results) >= 20:
                        break
            if len(results) >= 20:
                break

        return JSONResponse(results)

    @app.get("/api/memory/summary")
    async def memory_summary():
        items = sessions.list_sessions()
        total = len(items)
        finished = sum(1 for s in items if s.get("finished", False))
        total_msgs = sum(s.get("message_count", 0) for s in items)

        topics: dict[str, int] = {}
        for s in items:
            task = (s.get("task") or "").strip()
            if task:
                words = task.lower().split()[:4]
                for w in words:
                    w = w.strip(",.;:!?")
                    if len(w) > 3:
                        topics[w] = topics.get(w, 0) + 1
        top_topics = sorted(topics.items(), key=lambda x: -x[1])[:10]

        return JSONResponse({
            "total_sessions": total,
            "finished_sessions": finished,
            "in_progress_sessions": total - finished,
            "total_messages": total_msgs,
            "top_topics": [{"word": w, "count": c} for w, c in top_topics],
        })
