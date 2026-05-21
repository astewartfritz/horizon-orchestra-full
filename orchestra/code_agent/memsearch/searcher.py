from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from orchestra.code_agent.session import SessionManager


class MemorySearcher:
    """Full-text search through conversation history."""

    def __init__(self, session_dir: str = ""):
        self.mgr = SessionManager()
        if session_dir:
            self.mgr.session_dir = Path(session_dir)

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        q = query.lower()
        results = []

        sessions_info = self.mgr.list_sessions()
        for info in sessions_info:
            sid = info["id"]
            session = self.mgr.load(sid)
            if not session:
                continue

            task_match = q in (session.task or "").lower()
            result_match = q in (session.result or "").lower()

            message_matches = []
            for msg in getattr(session, "messages", []):
                content = getattr(msg, "content", "") or ""
                if q in content.lower():
                    message_matches.append({
                        "role": getattr(msg, "role", "unknown"),
                        "snippet": self._snippet(content, q),
                    })

            if task_match or result_match or message_matches:
                results.append({
                    "session_id": sid,
                    "task": session.task,
                    "task_match": task_match,
                    "result_match": result_match,
                    "message_matches": message_matches[:3],
                    "created_at": session.created_at,
                    "relevance": self._score(task_match, result_match, message_matches),
                })

        results.sort(key=lambda r: r["relevance"], reverse=True)
        return results[:max_results]

    def _snippet(self, text: str, query: str, context_chars: int = 80) -> str:
        idx = text.lower().find(query)
        if idx == -1:
            return text[:200]
        start = max(0, idx - context_chars)
        end = min(len(text), idx + len(query) + context_chars)
        snippet = text[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet

    def _score(self, task_match: bool, result_match: bool, msg_matches: list) -> float:
        score = 0.0
        if task_match:
            score += 2.0
        if result_match:
            score += 1.5
        score += len(msg_matches) * 0.5
        return score

    def stats(self) -> dict[str, Any]:
        sessions = self.mgr.list_sessions()
        total_msgs = 0
        for info in sessions:
            session = self.mgr.load(info["id"])
            if session:
                total_msgs += len(getattr(session, "messages", []))
        return {"sessions": len(sessions), "total_messages": total_msgs}
