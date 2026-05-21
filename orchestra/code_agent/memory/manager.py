from __future__ import annotations

from pathlib import Path
from typing import Any

from orchestra.code_agent.memory.base import MemoryEntry
from orchestra.code_agent.memory.buffer import BufferEntry, MemoryBuffer
from orchestra.code_agent.memory.consolidation import ConsolidationReport, MemoryConsolidation
from orchestra.code_agent.memory.graph import MemoryGraph
from orchestra.code_agent.memory.retrieval import MemoryRetrieval, RetrievalResult
from orchestra.code_agent.memory.store import MemoryStore


class MemoryManager:
    def __init__(
        self,
        store_path: str | Path = ".agent-memory.db",
        buffer_max_tokens: int = 32000,
        embedding_provider: str = "hash",
        embedding_api_key: str | None = None,
        llm: Any = None,
    ):
        self.store = MemoryStore(
            path=store_path,
            embedding_provider=embedding_provider,
            embedding_api_key=embedding_api_key,
        )
        self.buffer = MemoryBuffer(max_tokens=buffer_max_tokens)
        self.retrieval = MemoryRetrieval(self.store, self.buffer)
        self.consolidation = MemoryConsolidation(self.store, llm)
        self.graph = MemoryGraph(self.store)

    ## Working memory (buffer) operations

    def remember(
        self,
        content: str,
        role: str = "user",
        tier: str = "normal",
        source: str = "conversation",
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
        persist: bool = True,
    ) -> int:
        entry = BufferEntry(
            content=content,
            role=role,
            tier=tier,
            source=source,
            importance=importance,
            token_count=max(1, len(content) // 4),
            metadata=metadata or {},
        )
        evicted = self.buffer.add(entry)
        mid = 0
        if persist:
            mid = self.store.store(
                content=content,
                memory_type="working",
                tier=tier,
                role=role,
                source=source,
                importance=importance,
                metadata=metadata,
            )
            self.store.extract_and_store_entities(content, mid if mid else None)
        for ev in evicted:
            if ev.importance < 0.3:
                evicted_tier = "low"
            elif ev.importance < 0.7:
                evicted_tier = "normal"
            else:
                evicted_tier = "important"
            self.store.store(
                content=ev.content,
                memory_type="working",
                tier=evicted_tier,
                role=ev.role,
                source=ev.source,
                importance=ev.importance * 0.8,
                metadata=ev.metadata,
            )
        return mid

    def recall(self, query: str, top_k: int = 10) -> list[RetrievalResult]:
        return self.retrieval.retrieve(query, top_k=top_k)

    def recall_by_entity(self, entity_name: str, top_k: int = 10) -> list[RetrievalResult]:
        return self.retrieval.retrieve_by_entity(entity_name, top_k)

    def recall_recent(self, limit: int = 20) -> list[RetrievalResult]:
        return self.retrieval.retrieve_recent(limit=limit)

    def recall_important(self, min_importance: float = 0.7, top_k: int = 10) -> list[RetrievalResult]:
        return self.retrieval.retrieve_important(min_importance, top_k)

    def get_context(self, query: str, max_tokens: int = 8000) -> str:
        return self.retrieval.retrieve_context(query, max_tokens)

    def get_buffer_context(self, max_tokens: int | None = None) -> str:
        return self.buffer.get_context(max_tokens)

    def forget(self, memory_id: int) -> bool:
        return self.store.delete(memory_id)

    def update_importance(self, memory_id: int, importance: float) -> None:
        self.store.update_importance(memory_id, importance)

    def update_tier(self, memory_id: int, tier: str) -> None:
        self.store.update_tier(memory_id, tier)

    def get_memory(self, memory_id: int) -> Any:
        return self.store.get(memory_id)

    ## Consolidation operations

    async def consolidate(self, session_id: str | None = None) -> list[ConsolidationReport]:
        reports = []
        if session_id:
            r = await self.consolidation.summarize_session(session_id)
            if r:
                reports.append(r)
        r1 = await self.consolidation.deduplicate()
        reports.append(r1)
        r2 = await self.consolidation.tier_migration()
        reports.append(r2)
        r3 = await self.consolidation.cleanup()
        reports.append(r3)
        r4 = await self.consolidation.extract_entities()
        reports.append(r4)
        self.graph.auto_link_entities()
        return reports

    async def summarize_session(self, session_id: str) -> ConsolidationReport | None:
        return await self.consolidation.summarize_session(session_id)

    async def deduplicate(self) -> ConsolidationReport:
        return await self.consolidation.deduplicate()

    async def run_cleanup(self) -> ConsolidationReport:
        return await self.consolidation.cleanup()

    ## Graph operations

    def get_entity_network(self, center_name: str, depth: int = 2) -> dict[str, Any]:
        return self.graph.get_entity_network(center_name, depth)

    def find_path(self, source: str, target: str, max_depth: int = 4) -> list[Any]:
        return self.graph.find_path(source, target, max_depth)

    ## Stats

    def stats(self) -> dict[str, Any]:
        store_stats = self.store.stats()
        buffer_stats = self.buffer.stats()
        graph_stats = self.graph.stats()
        retrieval_stats = self.retrieval.stats()
        return {
            "store": store_stats,
            "buffer": buffer_stats,
            "graph": graph_stats,
            "retrieval": {k: v for k, v in retrieval_stats.items() if k not in ("buffer",)},
        }

    def search_memories(
        self,
        query: str,
        top_k: int = 10,
        memory_type: str | None = None,
    ) -> list[RetrievalResult]:
        return self.retrieval.retrieve(query, top_k=top_k, include_buffer=False)

    def list_memories(
        self,
        memory_type: str | None = None,
        tier: str | None = None,
        limit: int = 50,
    ) -> list[Any]:
        return self.store.list_memories(memory_type=memory_type, tier=tier, limit=limit)

    def clear(self) -> None:
        self.buffer.clear()
        self.store.clear()

    def close(self) -> None:
        self.store.close()
