from __future__ import annotations

from orchestra.code_agent.knowledge.base import KnowledgeBase
from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class KnowledgeTool(Tool):
    spec = ToolSpec(
        name="knowledge",
        description="Store and retrieve persistent knowledge across sessions. Semantic memory for the agent.",
        parameters={
            "query": {"type": "string", "description": "Search query or content to store"},
            "action": {
                "type": "string",
                "description": "store, search, recall, forget, stats",
                "default": "search",
            },
            "key": {"type": "string", "description": "Memory key (for store/recall/forget)", "default": ""},
            "source": {"type": "string", "description": "Source label (for store)", "default": "agent"},
            "tags": {"type": "string", "description": "Comma-separated tags (for store)", "default": ""},
            "top_k": {"type": "integer", "description": "Search result count", "default": 5},
        },
    )

    async def __call__(
        self, query: str = "", action: str = "search",
        key: str = "", source: str = "agent", tags: str = "",
        top_k: int = 5,
    ) -> ToolResult:
        try:
            kb = KnowledgeBase()

            if action == "store":
                if not key:
                    key = f"mem_{abs(hash(query)) % 1000000:06d}"
                tag_list = [t.strip() for t in tags.split(",") if t.strip()]
                kb.store(key, query, source=source, tags=tag_list)
                return ToolResult(output=f"Stored: {key} ({len(query)} chars)")

            elif action == "recall":
                entry = kb.recall(key)
                if not entry:
                    return ToolResult(output=f"(no memory: {key})")
                tags_str = ", ".join(entry.tags)
                return ToolResult(
                    output=f"Key: {entry.key}\nSource: {entry.source}\nTags: {tags_str}\n---\n{entry.content[:2000]}"
                )

            elif action == "forget":
                kb.forget(key)
                return ToolResult(output=f"Forgot: {key}")

            elif action == "stats":
                s = kb.stats()
                return ToolResult(output=f"Knowledge base: {s['entries']} entries\nSources: {', '.join(s['sources'])}")

            else:
                results = kb.search(query, top_k=top_k)
                if not results:
                    return ToolResult(output="(no results)")
                lines = [f"Top {len(results)} results for: {query}\n"]
                for r in results:
                    e = r.entry
                    lines.append(f"  [{r.score:.3f}] {e.key} ({e.source})")
                    lines.append(f"         {e.content[:120].strip()}")
                return ToolResult(output="\n".join(lines))

        except Exception as e:
            return ToolResult(error=str(e))
