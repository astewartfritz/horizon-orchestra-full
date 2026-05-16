from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any

from code_agent.memory.store import MemoryStore, StoredMemory

CONSOLIDATION_PROMPT = """Summarize the following conversation excerpts, preserving key decisions, facts, and insights:

{text}

Provide a concise summary covering: what was discussed, what decisions were made, what facts were established."""


@dataclass
class ConsolidationReport:
    operation: str
    source_count: int
    target_id: int | None
    summary: str
    tokens_saved: int
    duration_ms: float
    details: list[str] = field(default_factory=list)


class MemoryConsolidation:
    def __init__(self, store: MemoryStore, llm_provider: Any = None):
        self.store = store
        self.llm = llm_provider

    async def summarize_session(
        self,
        session_id: str,
        max_sources: int = 50,
    ) -> ConsolidationReport | None:
        start = time.time()
        memories = self.store.list_memories(session_id=session_id, limit=max_sources)
        if len(memories) < 3:
            return None

        text_parts = []
        for m in memories:
            text_parts.append(f"[{m.role}] {m.content[:500]}")
        text = "\n".join(text_parts)

        if self.llm and len(memories) > 10:
            from code_agent.llm.base import Message
            summary = await self._llm_summarize(text)
        else:
            summary = self._extractive_summary(text, memories)

        source_ids = [m.id for m in memories]
        tier = "episodic" if len(memories) > 20 else "working"
        target_id = self.store.store(
            content=summary,
            memory_type="episodic",
            tier=tier,
            role="system",
            source="consolidation",
            session_id=session_id,
            importance=0.8,
            metadata={"type": "session_summary", "source_count": len(memories), "original_ids": source_ids},
        )

        for m in memories:
            self.store.update_tier(m.id, "archived")

        self.store.log_consolidation(
            "summarize_session", source_ids, target_id, summary[:200],
        )

        tokens_before = sum(m.token_count for m in memories)
        tokens_after = len(summary) // 4
        return ConsolidationReport(
            operation="summarize_session",
            source_count=len(memories),
            target_id=target_id,
            summary=summary[:200],
            tokens_saved=tokens_before - tokens_after,
            duration_ms=(time.time() - start) * 1000,
            details=[f"Summarized {len(memories)} memories into 1"],
        )

    async def deduplicate(
        self,
        similarity_threshold: float = 0.92,
        memory_type: str | None = None,
    ) -> ConsolidationReport:
        start = time.time()
        memories = self.store.list_memories(memory_type=memory_type, limit=1000)
        if len(memories) < 2:
            return ConsolidationReport(
                operation="deduplicate", source_count=0, target_id=None,
                summary="Not enough memories", tokens_saved=0,
                duration_ms=(time.time() - start) * 1000,
            )

        removed = 0
        tokens_saved = 0
        details = []
        i = 0
        while i < len(memories):
            j = i + 1
            while j < len(memories):
                sim = self._content_similarity(memories[i].content, memories[j].content)
                if sim >= similarity_threshold:
                    self.store.delete(memories[j].id)
                    removed += 1
                    tokens_saved += memories[j].token_count
                    details.append(f"Removed duplicate: {memories[j].content[:80]}...")
                    memories.pop(j)
                else:
                    j += 1
            i += 1

        self.store.log_consolidation("deduplicate", [], None, f"Removed {removed} duplicates")
        return ConsolidationReport(
            operation="deduplicate",
            source_count=removed,
            target_id=None,
            summary=f"Removed {removed} duplicate memories",
            tokens_saved=tokens_saved,
            duration_ms=(time.time() - start) * 1000,
            details=details[:10],
        )

    async def tier_migration(self, max_age_days: float = 7.0) -> ConsolidationReport:
        start = time.time()
        cutoff = time.time() - (max_age_days * 86400)
        old_memories = self.store.list_memories(limit=5000)
        old_memories = [m for m in old_memories if m.created_at < cutoff and m.tier not in ("archived", "long_term")]

        migrated = 0
        for m in old_memories:
            access_rate = m.access_count / max(1, (time.time() - m.created_at) / 86400)
            if access_rate < 0.1:
                self.store.update_tier(m.id, "long_term")
                migrated += 1
            elif m.tier == "working":
                self.store.update_tier(m.id, "episodic")
                migrated += 1

        self.store.log_consolidation("tier_migration", [], None, f"Migrated {migrated} memories")
        return ConsolidationReport(
            operation="tier_migration",
            source_count=migrated,
            target_id=None,
            summary=f"Migrated {migrated} memories to lower tiers",
            tokens_saved=0,
            duration_ms=(time.time() - start) * 1000,
            details=[f"Migrated {migrated} old memories"],
        )

    async def cleanup(self, max_age_days: float = 90.0) -> ConsolidationReport:
        start = time.time()
        cutoff = time.time() - (max_age_days * 86400)
        deleted = 0
        tokens_saved = 0
        memories = self.store.list_memories(limit=5000)
        for m in memories:
            if m.created_at < cutoff and m.access_count == 0 and m.tier != "long_term":
                self.store.delete(m.id)
                deleted += 1
                tokens_saved += m.token_count

        self.store.log_consolidation("cleanup", [], None, f"Cleaned up {deleted} old memories")
        return ConsolidationReport(
            operation="cleanup",
            source_count=deleted,
            target_id=None,
            summary=f"Cleaned up {deleted} never-accessed memories older than {max_age_days} days",
            tokens_saved=tokens_saved,
            duration_ms=(time.time() - start) * 1000,
            details=[f"Deleted {deleted} stale memories"],
        )

    async def extract_entities(self, memory_type: str | None = None, limit: int = 100) -> ConsolidationReport:
        start = time.time()
        memories = self.store.list_memories(memory_type=memory_type, limit=limit)
        extracted = 0
        for m in memories:
            ids = self.store.extract_and_store_entities(m.content, m.id)
            extracted += len(ids)

        return ConsolidationReport(
            operation="extract_entities",
            source_count=len(memories),
            target_id=None,
            summary=f"Extracted {extracted} entity references from {len(memories)} memories",
            tokens_saved=0,
            duration_ms=(time.time() - start) * 1000,
            details=[f"Extracted {extracted} entity links"],
        )

    async def run_all(self) -> list[ConsolidationReport]:
        reports = []
        r1 = await self.deduplicate()
        reports.append(r1)
        r2 = await self.tier_migration()
        reports.append(r2)
        r3 = await self.cleanup()
        reports.append(r3)
        return reports

    @staticmethod
    def _content_similarity(a: str, b: str) -> float:
        a_words = set(re.findall(r"\w+", a.lower()))
        b_words = set(re.findall(r"\w+", b.lower()))
        if not a_words or not b_words:
            return 0.0
        intersection = a_words & b_words
        union = a_words | b_words
        return len(intersection) / len(union) if union else 0.0

    @staticmethod
    def _extractive_summary(text: str, memories: list[StoredMemory]) -> str:
        important = [m for m in memories if m.importance >= 0.7][:5]
        key_points = [f"- {m.content[:200]}" for m in important]
        stats = f"Session with {len(memories)} exchanges covering {len(important)} key points."
        return stats + "\n" + "\n".join(key_points)

    async def _llm_summarize(self, text: str) -> str:
        if not self.llm:
            return self._extractive_summary(text, [])
        try:
            from code_agent.llm.base import Message
            msg = Message(role="user", content=CONSOLIDATION_PROMPT.format(text=text[:8000]))
            response = await self.llm.chat([msg])
            return response.content[:2000]
        except Exception:
            return self._extractive_summary(text, [])
