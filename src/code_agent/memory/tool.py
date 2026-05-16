from __future__ import annotations

from typing import Any

from code_agent.tools.base import Tool, ToolResult, ToolSpec


class MemoryTool(Tool):
    def __init__(self, memory_manager: Any | None = None):
        self._manager = memory_manager
        self.spec = ToolSpec(
            name="memory",
            description="Store and retrieve memories across sessions. Actions: store, search, recall, forget, consolidate, stats, entities",
            parameters={
                "action": {
                    "type": "string",
                    "description": "Action: store, search, recall, forget, consolidate, stats, entities, recent, important",
                },
                "content": {
                    "type": "string",
                    "description": "Content to store (required for store action)",
                },
                "query": {
                    "type": "string",
                    "description": "Search query (required for search/recall actions)",
                },
                "memory_id": {
                    "type": "integer",
                    "description": "Memory ID to forget",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return (default: 10)",
                },
                "tier": {
                    "type": "string",
                    "description": "Memory tier: critical, important, normal, low (default: normal)",
                },
                "importance": {
                    "type": "number",
                    "description": "Importance score 0.0-1.0 (default: 0.5)",
                },
                "entity": {
                    "type": "string",
                    "description": "Entity name for entity-based recall",
                },
            },
        )

    def _get_manager(self):
        if self._manager is None:
            from code_agent.memory.manager import MemoryManager
            self._manager = MemoryManager()
        return self._manager

    async def __call__(self, **kwargs: Any) -> ToolResult:
        mgr = self._get_manager()
        action = kwargs.get("action", "").lower()

        if action == "store":
            content = kwargs.get("content", "")
            if not content:
                return ToolResult(error="content required for store")
            tier = kwargs.get("tier", "normal")
            importance = float(kwargs.get("importance", 0.5))
            mid = mgr.remember(content=content, tier=tier, importance=importance)
            return ToolResult(output=f"Stored memory #{mid} (tier={tier}, importance={importance})")

        elif action == "search":
            query = kwargs.get("query", "")
            top_k = int(kwargs.get("top_k", 10))
            if not query:
                return ToolResult(error="query required for search")
            results = mgr.recall(query, top_k=top_k)
            if not results:
                return ToolResult(output="No matching memories found.")
            lines = [f"Found {len(results)} memories:"]
            for i, r in enumerate(results, 1):
                lines.append(f"  {i}. [{r.tier}/{r.source}] ({r.score:.2f}) {r.content[:300]}")
            return ToolResult(output="\n".join(lines))

        elif action == "recall":
            query = kwargs.get("query", "")
            top_k = int(kwargs.get("top_k", 5))
            if not query:
                return ToolResult(error="query required for recall")
            context = mgr.get_context(query, max_tokens=top_k * 1000)
            if not context:
                return ToolResult(output="No relevant memories found.")
            return ToolResult(output=f"Relevant context:\n{context}")

        elif action == "recent":
            limit = int(kwargs.get("top_k", 20))
            results = mgr.recall_recent(limit=limit)
            if not results:
                return ToolResult(output="No recent memories.")
            lines = [f"Recent {len(results)} memories:"]
            for i, r in enumerate(results, 1):
                lines.append(f"  {i}. [{r.tier}] {r.content[:200]}")
            return ToolResult(output="\n".join(lines))

        elif action == "important":
            min_imp = float(kwargs.get("importance", 0.7))
            top_k = int(kwargs.get("top_k", 10))
            results = mgr.recall_important(min_importance=min_imp, top_k=top_k)
            if not results:
                return ToolResult(output="No important memories found.")
            lines = [f"Important memories (>{min_imp}):"]
            for i, r in enumerate(results, 1):
                lines.append(f"  {i}. ({r.importance:.2f}) [{r.source}] {r.content[:200]}")
            return ToolResult(output="\n".join(lines))

        elif action == "forget":
            mid = kwargs.get("memory_id")
            if not mid:
                return ToolResult(error="memory_id required for forget")
            if mgr.forget(int(mid)):
                return ToolResult(output=f"Forgot memory #{mid}")
            return ToolResult(error=f"Memory #{mid} not found")

        elif action == "consolidate":
            import asyncio
            reports = await mgr.consolidate()
            lines = ["Consolidation results:"]
            for r in reports:
                lines.append(f"  - {r.operation}: {r.summary} ({r.tokens_saved} tokens saved, {r.duration_ms:.0f}ms)")
            return ToolResult(output="\n".join(lines))

        elif action == "entities":
            entity_name = kwargs.get("entity", "")
            if entity_name:
                results = mgr.recall_by_entity(entity_name)
                network = mgr.get_entity_network(entity_name)
                lines = [f"Entity: {entity_name}"]
                lines.append(f"  Related: {len(network.get('edges', []))} connections")
                if results:
                    lines.append(f"  Memories: {len(results)}")
                    for r in results[:5]:
                        lines.append(f"    - {r.content[:150]}")
                return ToolResult(output="\n".join(lines))
            stats = mgr.stats()
            gs = stats.get("graph", {})
            lines = [f"Total entities: {gs.get('total_entities', 0)}"]
            by_type = gs.get("by_type", {})
            for t, c in by_type.items():
                lines.append(f"  {t}: {c}")
            return ToolResult(output="\n".join(lines))

        elif action == "stats":
            stats = mgr.stats()
            ss = stats.get("store", {})
            bs = stats.get("buffer", {})
            lines = [
                f"Store: {ss.get('total_memories', 0)} memories ({ss.get('total_tokens', 0)} tokens)",
                f"  by type: {ss.get('by_type', {})}",
                f"  by tier: {ss.get('by_tier', {})}",
                f"  entities: {ss.get('entities', 0)}",
                f"Buffer: {bs.get('total_entries', 0)} entries ({bs.get('current_tokens', 0)}/{bs.get('max_tokens', 0)} tokens, {bs.get('utilization', 0)}% full)",
            ]
            return ToolResult(output="\n".join(lines))

        return ToolResult(error=f"Unknown action: {action}. Use: store, search, recall, forget, consolidate, stats, entities, recent, important")
