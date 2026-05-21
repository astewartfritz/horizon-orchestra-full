from __future__ import annotations

from pathlib import Path

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class GrepTool(Tool):
    spec = ToolSpec(
        name="grep",
        description="Fast content search using regex patterns. Returns file paths and line numbers of matches sorted by modification time.",
        parameters={
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "Directory to search in (default: workspace)"},
            "include": {"type": "string", "description": "File pattern filter, e.g. *.py, *.{ts,tsx}"},
        },
    )

    async def __call__(
        self,
        pattern: str,
        path: str | None = None,
        include: str | None = None,
    ) -> ToolResult:
        try:
            root = Path(path) if path else Path.cwd()
            matches: list[str] = []

            if include:
                glob_patterns = [include]
            else:
                glob_patterns = ["**/*"]

            for gp in glob_patterns:
                for p in sorted(root.glob(gp)):
                    if not p.is_file():
                        continue
                    try:
                        text = p.read_text("utf-8", errors="replace")
                        for i, line in enumerate(text.splitlines(), 1):
                            import re
                            if re.search(pattern, line):
                                rel = p.relative_to(root)
                                matches.append(f"{rel}:{i}: {line.strip()[:200]}")
                    except Exception:
                        continue

            if not matches:
                return ToolResult(output="(no matches)")

            return ToolResult(output="\n".join(matches[:200]))
        except Exception as e:
            return ToolResult(error=str(e))
