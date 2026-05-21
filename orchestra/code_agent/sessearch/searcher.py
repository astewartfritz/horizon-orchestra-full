from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.session import SessionManager


@dataclass
class SessionHit:
    session_id: str = ""
    task: str = ""
    score: float = 0.0
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "task": self.task,
                "score": round(self.score, 3), "snippet": self.snippet[:200]}


class SessionSearchEngine:
    """Semantic search through all sessions using keyword + embedding similarity."""

    def __init__(self):
        self.mgr = SessionManager()

    def _simple_embed(self, text: str, dim: int = 32) -> list[float]:
        vec = [0.0] * dim
        tokens = re.findall(r'\w+', text.lower())
        for i, token in enumerate(tokens):
            h = hash(token + str(i)) % dim
            vec[abs(h)] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def _cosine_sim(self, a: list[float], b: list[float]) -> float:
        return sum(x * y for x, y in zip(a, b))

    def search(self, query: str, top_k: int = 10) -> list[SessionHit]:
        q_emb = self._simple_embed(query)
        query_lower = query.lower()
        results: list[SessionHit] = []

        sessions = self.mgr.list_sessions()
        for info in sessions:
            sid = info["id"]
            session = self.mgr.load(sid)
            if not session:
                continue

            task = session.task or ""
            content = (session.result or "") + " " + task
            for msg in getattr(session, "messages", []):
                content += " " + (getattr(msg, "content", "") or "")

            # Keyword score
            kw_score = 0.0
            if query_lower in task.lower():
                kw_score += 3.0
            if query_lower in (session.result or "").lower():
                kw_score += 2.0
            kw_score += content.lower().count(query_lower) * 0.2

            # Embedding similarity
            content_emb = self._simple_embed(content[:2000])
            emb_score = self._cosine_sim(q_emb, content_emb)

            combined = kw_score + emb_score * 5.0

            if combined > 0:
                snippet = self._find_snippet(content, query)
                results.append(SessionHit(
                    session_id=sid, task=task[:100],
                    score=combined, snippet=snippet,
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _find_snippet(self, content: str, query: str, window: int = 100) -> str:
        idx = content.lower().find(query.lower())
        if idx == -1:
            return content[:200]
        start = max(0, idx - window)
        end = min(len(content), idx + len(query) + window)
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet

    def stats(self) -> dict[str, Any]:
        sessions = self.mgr.list_sessions()
        total_msgs = 0
        for info in sessions:
            session = self.mgr.load(info["id"])
            if session:
                total_msgs += len(getattr(session, "messages", []))
        return {"sessions_indexed": len(sessions), "total_messages": total_msgs}
