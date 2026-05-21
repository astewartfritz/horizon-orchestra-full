from __future__ import annotations

import glob as glob_mod
import os
from pathlib import Path

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class ReadTool(Tool):
    spec = ToolSpec(
        name="read",
        description="Read a file from the filesystem (up to 2000 lines). Use offset/limit to read specific sections.",
        parameters={
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "offset": {"type": "integer", "description": "Line number to start from (1-indexed)", "default": 1},
            "limit": {"type": "integer", "description": "Max lines to return", "default": 2000},
        },
    )

    async def __call__(self, file_path: str, offset: int = 1, limit: int = 2000) -> ToolResult:
        try:
            p = Path(file_path)
            if not p.exists():
                return ToolResult(error=f"File not found: {file_path}")
            if p.is_dir():
                entries = sorted(p.iterdir())
                lines = []
                for e in entries:
                    suffix = "/" if e.is_dir() else ""
                    lines.append(f"{e.name}{suffix}")
                return ToolResult(output="\n".join(lines) if lines else "(empty directory)")
            text = p.read_text("utf-8")
            lines = text.splitlines()
            total = len(lines)
            start = max(0, offset - 1)
            end = start + limit
            chunk = lines[start:end]
            result = "\n".join(
                f"{i + 1}: {line}" for i, line in enumerate(chunk, start=start + 1)
            )
            if end < total:
                result += f"\n... ({total - end} more lines)"
            return ToolResult(output=result)
        except Exception as e:
            return ToolResult(error=str(e))


class WriteTool(Tool):
    spec = ToolSpec(
        name="write",
        description="Write content to a file (creates parent dirs automatically). Overwrites existing files.",
        parameters={
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "content": {"type": "string", "description": "Content to write"},
        },
    )

    async def __call__(self, file_path: str, content: str) -> ToolResult:
        try:
            p = Path(file_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, "utf-8")
            return ToolResult(output=f"Wrote {len(content)} bytes to {file_path}")
        except Exception as e:
            return ToolResult(error=str(e))


class EditTool(Tool):
    spec = ToolSpec(
        name="edit",
        description="Perform exact string replacement in an existing file.",
        parameters={
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "old_string": {"type": "string", "description": "Text to find (must match exactly)"},
            "new_string": {"type": "string", "description": "Replacement text"},
        },
    )

    async def __call__(self, file_path: str, old_string: str, new_string: str) -> ToolResult:
        try:
            p = Path(file_path)
            if not p.exists():
                return ToolResult(error=f"File not found: {file_path}")
            text = p.read_text("utf-8")
            if old_string not in text:
                return ToolResult(error=f"old_string not found in {file_path}")
            if text.count(old_string) > 1:
                return ToolResult(error="Found multiple matches for old_string. Provide more surrounding context.")
            text = text.replace(old_string, new_string, 1)
            p.write_text(text, "utf-8")
            return ToolResult(output=f"Edited {file_path}")
        except Exception as e:
            return ToolResult(error=str(e))


class GlobTool(Tool):
    spec = ToolSpec(
        name="glob",
        description="Fast file pattern matching. Finds files by glob patterns like **/*.py or src/**/*.ts",
        parameters={
            "pattern": {"type": "string", "description": "Glob pattern to match"},
            "path": {"type": "string", "description": "Root directory (default: workspace)"},
        },
    )

    async def __call__(self, pattern: str, path: str | None = None) -> ToolResult:
        try:
            root = Path(path) if path else Path.cwd()
            matches = sorted(glob_mod.glob(pattern, root_dir=root, recursive=True))
            return ToolResult(
                output="\n".join(matches) if matches else "(no matches)"
            )
        except Exception as e:
            return ToolResult(error=str(e))
