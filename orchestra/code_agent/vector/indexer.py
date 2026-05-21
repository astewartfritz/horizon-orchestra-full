from __future__ import annotations

from pathlib import Path

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec
from orchestra.code_agent.vector.engine import VectorEngine


class IndexerTool(Tool):
    spec = ToolSpec(
        name="index",
        description="Index code files for semantic vector search. Run this before using 'semsearch'.",
        parameters={
            "path": {"type": "string", "description": "File or directory to index", "default": "."},
            "pattern": {"type": "string", "description": "Glob pattern (default **/*.py)", "default": "**/*.py"},
            "action": {
                "type": "string",
                "description": "Action: index (default), remove, stats, search",
                "default": "index",
            },
            "query": {"type": "string", "description": "Search query (used with action=search)"},
            "top_k": {"type": "integer", "description": "Number of results (used with action=search)", "default": 5},
        },
    )

    async def __call__(
        self,
        path: str = ".",
        pattern: str = "**/*.py",
        action: str = "index",
        query: str = "",
        top_k: int = 5,
    ) -> ToolResult:
        try:
            engine = VectorEngine()

            if action == "index":
                p = Path(path)
                if p.is_file():
                    count = engine.index_file(str(p))
                    return ToolResult(output=f"Indexed {count} chunks from {path}")
                else:
                    count = engine.index_directory(str(p), pattern)
                    return ToolResult(output=f"Indexed {count} chunks from {path} matching {pattern}")

            elif action == "remove":
                engine.remove_file(path)
                return ToolResult(output=f"Removed {path} from index")

            elif action == "stats":
                s = engine.stats()
                return ToolResult(output=f"Index stats: {s['chunks']} chunks across {s['files']} files")

            elif action == "search":
                if not query:
                    return ToolResult(error="query required for action=search")
                results = engine.search(query, top_k=top_k, file_filter=path if path != "." else None)
                if not results:
                    return ToolResult(output="(no results found)")
                lines = [f"Top {len(results)} results for: {query}\n"]
                for r in results:
                    chunk = r.chunk
                    lines.append(
                        f"  [{r.score:.3f}] {chunk.file_path}:{chunk.start_line}-{chunk.end_line} "
                        f"({chunk.chunk_type}{':' + chunk.name if chunk.name else ''})"
                    )
                    lines.append(f"       {chunk.content[:120].strip()}")
                return ToolResult(output="\n".join(lines))

            else:
                return ToolResult(error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(error=str(e))
