from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Any


def rename_symbol(
    file_path: str,
    old_name: str,
    new_name: str,
    symbol_type: str = "auto",
    dry_run: bool = False,
) -> dict[str, Any]:
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"success": False, "error": f"Syntax error: {e}"}

    if symbol_type in ("function", "class", "auto"):
        # Detect if old_name is a function or class in this file
        detected = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == old_name:
                detected = True
                break
            if isinstance(node, ast.ClassDef) and node.name == old_name:
                detected = True
                break

        if not detected and symbol_type == "auto":
            return {"success": False, "error": f"Symbol '{old_name}' not found in file"}
    else:
        # variable rename: find Name nodes
        pass

    # Simple text-based replacement with word boundaries
    import re
    pattern = re.compile(r'\b' + re.escape(old_name) + r'\b')
    new_source = pattern.sub(new_name, source)

    if dry_run:
        changes = sum(1 for _ in pattern.finditer(source))
        return {
            "success": True,
            "changes": changes,
            "preview": new_source[:2000],
        }

    path.write_text(new_source, encoding="utf-8")
    changes = sum(1 for _ in pattern.finditer(source))
    return {"success": True, "changes": changes, "message": f"Renamed {old_name} -> {new_name} ({changes} occurrences)"}


async def rename_tool(**kwargs: Any) -> str:
    fp = kwargs.get("file_path", "")
    old = kwargs.get("old_name", "")
    new = kwargs.get("new_name", "")
    dry = str(kwargs.get("dry_run", "")).lower() in ("true", "1", "yes")
    if not fp or not old or not new:
        return "Error: file_path, old_name, new_name required"
    result = rename_symbol(fp, old, new, dry_run=dry)
    if result["success"]:
        if dry:
            return f"[dry-run] {result['changes']} changes\n\nPreview:\n{result['preview']}"
        return result["message"]
    return f"Error: {result['error']}"
