from __future__ import annotations

from typing import Any

from code_agent.tools.base import Tool, ToolResult, ToolSpec
from code_agent.transform.rename import rename_symbol
from code_agent.transform.extract import extract_function
from code_agent.transform.inline import inline_variable


class TransformTool(Tool):
    spec = ToolSpec(
        name="transform",
        description="AST-safe code transformations: rename symbols, extract functions, inline variables.",
        parameters={
            "file_path": {"type": "string", "description": "Path to source file"},
            "action": {"type": "string", "description": "rename, extract, inline", "default": "rename"},
            "old_name": {"type": "string", "description": "Old symbol name (rename) or function name (extract)", "default": ""},
            "new_name": {"type": "string", "description": "New symbol name (rename) or new function name (extract)", "default": ""},
            "variable_name": {"type": "string", "description": "Variable name to inline", "default": ""},
            "dry_run": {"type": "boolean", "description": "Preview changes without applying", "default": False},
        },
    )

    async def __call__(
        self, file_path: str = "", action: str = "rename",
        old_name: str = "", new_name: str = "",
        variable_name: str = "", dry_run: bool = False,
    ) -> ToolResult:
        try:
            if action == "rename":
                if not file_path or not old_name or not new_name:
                    return ToolResult(error="file_path, old_name, new_name required")
                result = rename_symbol(file_path, old_name, new_name, dry_run=dry_run)
                if result["success"]:
                    if dry_run:
                        return ToolResult(output=f"[dry-run] {result['changes']} changes\n\nPreview:\n{result.get('preview', '')[:2000]}")
                    return ToolResult(output=result["message"])
                return ToolResult(error=result.get("error", "Unknown error"))

            elif action == "extract":
                if not file_path or not old_name:
                    return ToolResult(error="file_path, function_name required")
                new_fn = new_name or f"{old_name}_part"
                result = extract_function(file_path, old_name, new_fn, dry_run=dry_run)
                if result["success"]:
                    if dry_run:
                        return ToolResult(output=f"[dry-run] Preview:\n{result['preview']}")
                    return ToolResult(output=result["message"])
                return ToolResult(error=result.get("error", "Unknown error"))

            elif action == "inline":
                if not file_path or not variable_name:
                    return ToolResult(error="file_path, variable_name required")
                result = inline_variable(file_path, variable_name, dry_run=dry_run)
                if result["success"]:
                    if dry_run:
                        return ToolResult(output=f"[dry-run] {result['changes']} changes\n\nPreview:\n{result['preview']}")
                    return ToolResult(output=result["message"])
                return ToolResult(error=result.get("error", "Unknown error"))

            return ToolResult(error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(error=str(e))
