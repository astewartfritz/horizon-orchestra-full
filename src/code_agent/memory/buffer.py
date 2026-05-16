from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from code_agent.memory.base import MemoryEntry


@dataclass
class BufferEntry:
    content: str
    role: str = "user"
    tier: str = "normal"
    source: str = "conversation"
    importance: float = 0.5
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_memory_entry(self) -> MemoryEntry:
        meta = dict(self.metadata)
        meta.update({"tier": self.tier, "importance": self.importance, "source": self.source, "timestamp": self.timestamp})
        return MemoryEntry(role=self.role, content=self.content, metadata=meta)

    @classmethod
    def from_memory_entry(cls, entry: MemoryEntry, tier: str = "normal", importance: float = 0.5, source: str = "conversation") -> BufferEntry:
        meta = entry.metadata or {}
        return cls(
            content=entry.content,
            role=entry.role,
            tier=meta.get("tier", tier),
            importance=meta.get("importance", importance),
            source=meta.get("source", source),
            token_count=max(1, len(entry.content) // 4),
            metadata=meta,
            timestamp=meta.get("timestamp", time.time()),
        )


class MemoryBuffer:
    def __init__(self, max_tokens: int = 32000, reserve_tokens: int | None = None):
        self.max_tokens = max_tokens
        self.reserve_tokens = reserve_tokens if reserve_tokens is not None else min(max_tokens // 4, 8000)
        self._entries: list[BufferEntry] = []

    @property
    def budget(self) -> int:
        return self.max_tokens - self.reserve_tokens

    @property
    def current_tokens(self) -> int:
        return sum(e.token_count for e in self._entries)

    @property
    def available_tokens(self) -> int:
        return self.budget - self.current_tokens

    @property
    def utilization(self) -> float:
        if self.budget <= 0:
            return 1.0
        return min(1.0, self.current_tokens / self.budget)

    def add(self, entry: BufferEntry) -> list[BufferEntry]:
        self._entries.append(entry)
        evicted = []
        while self.current_tokens > self.budget and len(self._entries) > 1 and self.budget > 0:
            evicted.append(self._evict_one())
        return evicted

    def _evict_one(self) -> BufferEntry:
        tiers = {"low": 0, "normal": 1, "important": 2, "critical": 3}
        oldest_non_critical = min(
            (e for e in self._entries if tiers.get(e.tier, 1) < 3),
            key=lambda e: (tiers.get(e.tier, 1), -e.importance, e.timestamp),
            default=None,
        )
        if oldest_non_critical:
            self._entries.remove(oldest_non_critical)
            return oldest_non_critical
        oldest = min(self._entries, key=lambda e: e.timestamp)
        self._entries.remove(oldest)
        return oldest

    def get_tier(self, tier: str) -> list[BufferEntry]:
        return [e for e in self._entries if e.tier == tier]

    def get_context(self, max_tokens: int | None = None) -> str:
        max_tok = max_tokens or self.budget
        entries = sorted(self._entries, key=lambda e: (
            {"critical": 0, "important": 1, "normal": 2, "low": 3}.get(e.tier, 2),
            -e.importance,
            e.timestamp,
        ))
        parts = []
        used = 0
        for e in entries:
            if used + e.token_count > max_tok:
                break
            parts.append(f"[{e.role.upper()}] {e.content}")
            used += e.token_count
        return "\n".join(parts)

    def get_recent(self, n: int = 10) -> list[BufferEntry]:
        return self._entries[-n:]

    def search(self, query: str, top_k: int = 5) -> list[tuple[BufferEntry, float]]:
        query_lower = query.lower()
        scored: list[tuple[BufferEntry, float]] = []
        for e in self._entries:
            content_lower = e.content.lower()
            score = 0.0
            for term in query_lower.split():
                score += content_lower.count(term)
            recency = 1.0 / (1.0 + (time.time() - e.timestamp))
            tier_score = {"critical": 3.0, "important": 2.0, "normal": 1.0, "low": 0.5}.get(e.tier, 1.0)
            total = score * tier_score + recency
            if total > 0:
                scored.append((e, total))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def clear(self, tier: str | None = None) -> None:
        if tier:
            self._entries = [e for e in self._entries if e.tier != tier]
        else:
            self._entries = []

    def clear_expired(self, max_age_seconds: float = 3600) -> int:
        cutoff = time.time() - max_age_seconds
        before = len(self._entries)
        self._entries = [
            e for e in self._entries
            if e.tier == "critical" or e.timestamp > cutoff
        ]
        return before - len(self._entries)

    def stats(self) -> dict[str, Any]:
        tiers: dict[str, int] = {}
        for e in self._entries:
            tiers[e.tier] = tiers.get(e.tier, 0) + 1
        return {
            "total_entries": len(self._entries),
            "current_tokens": self.current_tokens,
            "max_tokens": self.max_tokens,
            "utilization": round(self.utilization * 100, 1),
            "available_tokens": self.available_tokens,
            "by_tier": tiers,
        }
