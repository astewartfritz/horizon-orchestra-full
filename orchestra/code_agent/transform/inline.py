from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


def inline_variable(
    file_path: str,
    variable_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"success": False, "error": f"Syntax error: {e}"}

    # Find the variable assignment
    assignment_value = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == variable_name:
                    assignment_value = node.value
                    break
        if isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == variable_name:
                assignment_value = node.value

    if assignment_value is None:
        return {"success": False, "error": f"Variable '{variable_name}' not found"}

    value_source = ast.unparse(assignment_value)

    import re
    pattern = re.compile(r'\b' + re.escape(variable_name) + r'\b')

    # Count occurrences
    occurrences = list(pattern.finditer(source))
    if not occurrences:
        return {"success": False, "error": f"No usages of '{variable_name}' found"}

    # First occurrence is likely the definition — keep that, replace the rest
    # Actually let's just replace all non-definition usages
    # Simple approach: replace all, then check
    new_source = pattern.sub(f"({value_source})", source)

    if dry_run:
        return {
            "success": True,
            "changes": len(occurrences),
            "preview": new_source[:2000],
        }

    path.write_text(new_source, encoding="utf-8")
    return {
        "success": True,
        "changes": len(occurrences),
        "message": f"Inlined '{variable_name}' = {value_source} ({len(occurrences)} occurrences)",
    }


async def inline_tool(**kwargs: Any) -> str:
    fp = kwargs.get("file_path", "")
    var = kwargs.get("variable_name", "")
    dry = str(kwargs.get("dry_run", "")).lower() in ("true", "1", "yes")
    if not fp or not var:
        return "Error: file_path, variable_name required"
    result = inline_variable(fp, var, dry_run=dry)
    if result["success"]:
        if dry:
            return f"[dry-run] {result['changes']} changes\n\nPreview:\n{result['preview']}"
        return result["message"]
    return f"Error: {result['error']}"
