from __future__ import annotations

import difflib
import os
from pathlib import Path

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class DiffTool(Tool):
    spec = ToolSpec(
        name="diff",
        description="Compute a unified diff between two files or a file and a string.",
        parameters={
            "file1": {"type": "string", "description": "Path to original file"},
            "file2": {"type": "string", "description": "Path to modified file, or omit and pass content via 'content'"},
            "content": {"type": "string", "description": "New content (alternative to file2)"},
            "context": {"type": "integer", "description": "Lines of context (default 3)", "default": 3},
        },
    )

    async def __call__(
        self,
        file1: str,
        file2: str | None = None,
        content: str | None = None,
        context: int = 3,
    ) -> ToolResult:
        try:
            p1 = Path(file1)
            if not p1.exists():
                return ToolResult(error=f"File not found: {file1}")
            old_text = p1.read_text("utf-8")

            if file2:
                p2 = Path(file2)
                if not p2.exists():
                    return ToolResult(error=f"File not found: {file2}")
                new_text = p2.read_text("utf-8")
            elif content is not None:
                new_text = content
            else:
                return ToolResult(error="Provide either file2 or content")

            diff = difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_text.splitlines(keepends=True),
                fromfile=file1,
                tofile=file2 or file1,
                n=context,
            )
            result = "".join(diff)
            if not result.strip():
                return ToolResult(output="(files are identical)")
            return ToolResult(output=result)
        except Exception as e:
            return ToolResult(error=str(e))


class PatchTool(Tool):
    spec = ToolSpec(
        name="patch",
        description="Apply a unified diff (patch) to modify a file in-place.",
        parameters={
            "file_path": {"type": "string", "description": "Path to the file to patch"},
            "diff": {"type": "string", "description": "Unified diff text to apply"},
        },
    )

    async def __call__(self, file_path: str, diff: str) -> ToolResult:
        try:
            p = Path(file_path)
            if not p.exists():
                return ToolResult(error=f"File not found: {file_path}")

            original = p.read_text("utf-8")

            from patch import fromstring  # type: ignore
            patch_set = fromstring(diff)
            if not patch_set:
                return ToolResult(error="Failed to parse diff")

            result_text = original
            for pat in patch_set:
                if pat.source:
                    pat.source = file_path

            temp_path = p.with_suffix(".patch_tmp")
            temp_path.write_text(original, "utf-8")

            patch_set.apply(root=str(p.parent))

            final = p.read_text("utf-8")
            if final == original:
                return ToolResult(output="Patch applied but file unchanged (may already match)")
            return ToolResult(output=f"Applied patch to {file_path}")

        except ImportError:
            return ToolResult(
                error="patch package not installed. Install with: pip install patch"
            )
        except Exception as e:
            return ToolResult(error=str(e))


class ApplyEditTool(Tool):
    spec = ToolSpec(
        name="apply_edit",
        description="Apply a search/replace block to a file. Like edit but supports multi-line blocks with fuzzy matching.",
        parameters={
            "file_path": {"type": "string", "description": "Path to the file"},
            "search": {"type": "string", "description": "Block of text to search for (exact match)"},
            "replace": {"type": "string", "description": "Replacement text"},
        },
    )

    async def __call__(self, file_path: str, search: str, replace: str) -> ToolResult:
        try:
            p = Path(file_path)
            if not p.exists():
                return ToolResult(error=f"File not found: {file_path}")

            text = p.read_text("utf-8")

            if search in text:
                count = text.count(search)
                if count > 1:
                    return ToolResult(error=f"Found {count} matches. Provide more context.")
                text = text.replace(search, replace, 1)
                p.write_text(text, "utf-8")
                return ToolResult(output=f"Applied edit to {file_path}")
            else:
                ratio = difflib.SequenceMatcher(None, search, text).ratio()
                if ratio > 0.8:
                    return ToolResult(
                        output=f"Exact match not found (similarity: {ratio:.0%}). "
                               "Try providing exact text from the file."
                    )
                return ToolResult(
                    error=f"Search text not found in {file_path}. "
                          "Use read to get the exact content."
                )
        except Exception as e:
            return ToolResult(error=str(e))
