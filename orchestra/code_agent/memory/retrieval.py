from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.memory.buffer import BufferEntry, MemoryBuffer
from orchestra.code_agent.memory.store import MemoryStore, StoredMemory


@dataclass
class RetrievalResult:
    content: str
    score: float
    source: str
    memory_type: str
    tier: str
    session_id: str
    created_at: float
    importance: float
    memory_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "content": self.content[:200],
            "score": round(self.score, 4),
            "source": self.source,
            "memory_type": self.memory_type,
            "tier": self.tier,
            "session_id": self.session_id,
            "created_at": self.created_at,
            "importance": self.importance,
        }


class MemoryRetrieval:
    def __init__(
        self,
        store: MemoryStore,
        buffer: MemoryBuffer | None = None,
    ):
        self.store = store
        self.buffer = buffer

    def retrieve(
        self,
        query: str,
        top_k: int = 10,
        include_buffer: bool = True,
        memory_types: list[str] | None = None,
        min_score: float = 0.1,
    ) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []

        if include_buffer and self.buffer:
            buffer_hits = self.buffer.search(query, top_k=top_k)
            for entry, score in buffer_hits:
                if score >= min_score:
                    results.append(RetrievalResult(
                        content=entry.content,
                        score=score * 0.8,
                        source=entry.source,
                        memory_type="buffer",
                        tier=entry.tier,
                        session_id="",
                        created_at=entry.timestamp,
                        importance=entry.importance,
                    ))

        store_results = self.store.search(query, top_k=top_k)
        for mem, score in store_results:
            if score >= min_score:
                if memory_types and mem.memory_type not in memory_types:
                    continue
                results.append(RetrievalResult(
                    content=mem.content,
                    score=score,
                    source=mem.source,
                    memory_type=mem.memory_type,
                    tier=mem.tier,
                    session_id=mem.session_id,
                    created_at=mem.created_at,
                    importance=mem.importance,
                    memory_id=mem.id,
                ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def retrieve_recent(self, limit: int = 20, include_buffer: bool = True) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []

        if include_buffer and self.buffer:
            for entry in self.buffer.get_recent(limit):
                results.append(RetrievalResult(
                    content=entry.content,
                    score=1.0,
                    source=entry.source,
                    memory_type="buffer",
                    tier=entry.tier,
                    session_id="",
                    created_at=entry.timestamp,
                    importance=entry.importance,
                ))

        store_memories = self.store.list_memories(limit=limit)
        for mem in store_memories:
            results.append(RetrievalResult(
                content=mem.content,
                score=0.5,
                source=mem.source,
                memory_type=mem.memory_type,
                tier=mem.tier,
                session_id=mem.session_id,
                created_at=mem.created_at,
                importance=mem.importance,
                memory_id=mem.id,
            ))

        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    def retrieve_by_entity(self, entity_name: str, top_k: int = 10) -> list[RetrievalResult]:
        memories = self.store.get_memories_by_entity(entity_name)
        results = []
        for mem in memories[:top_k]:
            results.append(RetrievalResult(
                content=mem.content,
                score=1.0,
                source=mem.source,
                memory_type=mem.memory_type,
                tier=mem.tier,
                session_id=mem.session_id,
                created_at=mem.created_at,
                importance=mem.importance,
                memory_id=mem.id,
            ))
        return results

    def retrieve_important(self, min_importance: float = 0.7, top_k: int = 10) -> list[RetrievalResult]:
        results: list[RetrievalResult] = []

        if self.buffer:
            for entry in self.buffer._entries:
                if entry.importance >= min_importance:
                    results.append(RetrievalResult(
                        content=entry.content,
                        score=entry.importance,
                        source=entry.source,
                        memory_type="buffer",
                        tier=entry.tier,
                        session_id="",
                        created_at=entry.timestamp,
                        importance=entry.importance,
                    ))

        store_results = self.store.search(
            query="important",
            top_k=top_k,
            min_importance=min_importance,
        )
        for mem, score in store_results:
            results.append(RetrievalResult(
                content=mem.content,
                score=score,
                source=mem.source,
                memory_type=mem.memory_type,
                tier=mem.tier,
                session_id=mem.session_id,
                created_at=mem.created_at,
                importance=mem.importance,
                memory_id=mem.id,
            ))

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def retrieve_context(self, query: str, max_tokens: int = 8000) -> str:
        results = self.retrieve(query, top_k=20)
        parts = []
        used = 0
        for r in results:
            estimated = len(r.content) // 4
            if used + estimated > max_tokens:
                break
            label = f"[{r.source}/{r.tier}]"
            parts.append(f"{label} {r.content[:500]}")
            used += estimated
        if not parts:
            return ""
        return "\n\n".join(parts)

    def stats(self) -> dict[str, Any]:
        store_stats = self.store.stats()
        if self.buffer:
            buffer_stats = self.buffer.stats()
            store_stats["buffer"] = buffer_stats
        return store_stats
