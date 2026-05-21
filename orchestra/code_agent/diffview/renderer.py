from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any


class DiffRenderer:
    """Render code diffs in multiple formats (terminal, HTML, markdown, unified)."""

    @staticmethod
    def unified(old_text: str, new_text: str, context: int = 3) -> str:
        return "\n".join(difflib.unified_diff(
            old_text.split("\n"), new_text.split("\n"),
            lineterm="", n=context,
        ))

    @staticmethod
    def terminal(old_text: str, new_text: str, context: int = 2) -> str:
        diff = difflib.unified_diff(
            old_text.split("\n"), new_text.split("\n"),
            lineterm="", n=context,
        )
        lines = []
        for line in diff:
            if line.startswith("+"):
                lines.append(f"\033[32m{line}\033[0m")
            elif line.startswith("-"):
                lines.append(f"\033[31m{line}\033[0m")
            elif line.startswith("@@"):
                lines.append(f"\033[36m{line}\033[0m")
            else:
                lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def markdown(old_text: str, new_text: str, filename: str = "") -> str:
        diff = difflib.unified_diff(
            old_text.split("\n"), new_text.split("\n"),
            lineterm="", n=3,
        )
        lines = list(diff)
        if not lines:
            return "(no changes)"

        header = f"### {filename}\n\n" if filename else ""
        result = [header + "```diff"]
        result.extend(lines)
        result.append("```")
        return "\n".join(result)

    @staticmethod
    def html(old_text: str, new_text: str, filename: str = "") -> str:
        diff = difflib.HtmlDiff()
        return diff.make_file(
            old_text.split("\n"), new_text.split("\n"),
            fromdesc=f"old: {filename}" if filename else "old",
            todesc=f"new: {filename}" if filename else "new",
        )

    @staticmethod
    def file_unified(old_path: str, new_path: str) -> str:
        old = Path(old_path).read_text(encoding="utf-8", errors="ignore")
        new = Path(new_path).read_text(encoding="utf-8", errors="ignore")
        return DiffRenderer.unified(old, new)

    @staticmethod
    def stats(old_text: str, new_text: str) -> dict[str, Any]:
        old_lines = old_text.split("\n")
        new_lines = new_text.split("\n")
        matcher = difflib.SequenceMatcher(None, old_lines, new_lines)
        added = sum(1 for tag, _, _, _, _ in matcher.get_opcodes() if tag == "insert")
        removed = sum(1 for tag, _, _, _, _ in matcher.get_opcodes() if tag == "delete")
        changed = sum(1 for tag, _, _, _, _ in matcher.get_opcodes() if tag == "replace")
        return {
            "old_lines": len(old_lines),
            "new_lines": len(new_lines),
            "added": added,
            "removed": removed,
            "changed": changed,
            "total_changes": added + removed + changed,
        }

    @staticmethod
    def side_by_side(old_text: str, new_text: str, width: int = 80) -> str:
        old_lines = old_text.split("\n")
        new_lines = new_text.split("\n")
        half = width // 2 - 2
        result = []
        result.append("-" * width)
        result.append(f"{'OLD':{half}} | {'NEW':{half}}")
        result.append("-" * width)

        max_len = max(len(old_lines), len(new_lines))
        for i in range(max_len):
            old = old_lines[i] if i < len(old_lines) else ""
            new = new_lines[i] if i < len(new_lines) else ""
            old = old[:half].ljust(half)
            new = new[:half].ljust(half)
            marker = " " if old == new else "*"
            result.append(f"{old} | {new} {marker}")

        return "\n".join(result)
