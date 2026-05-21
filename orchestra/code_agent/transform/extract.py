from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from typing import Any


def extract_function(
    file_path: str,
    function_name: str,
    new_function_name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    path = Path(file_path)
    source = path.read_text(encoding="utf-8")

    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        return {"success": False, "error": f"Syntax error: {e}"}

    target_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            target_node = node
            break

    if target_node is None:
        return {"success": False, "error": f"Function '{function_name}' not found"}

    if len(target_node.body) < 2:
        return {"success": False, "error": "Function body too small to extract"}

    # Find the last few statements to extract
    extracted = target_node.body[-1]
    remaining = target_node.body[:-1]

    # Generate the new function call
    call_args = []
    for arg in target_node.args.args + target_node.args.posonlyargs + target_node.args.kwonlyargs:
        call_args.append(arg.arg)

    # Reconstruct source lines
    lines = source.split("\n")
    target_lineno = target_node.lineno
    target_end = target_node.end_lineno or target_lineno

    indent = " " * (target_node.col_offset if hasattr(target_node, 'col_offset') else 0)

    new_func_body = textwrap.dedent(ast.unparse(extracted))
    call_str = f"{new_function_name}({', '.join(call_args)})"

    new_func_def = (
        f"\n{indent}def {new_function_name}({', '.join(call_args)}):\n"
        f"{indent}    {new_func_body.replace(chr(10), chr(10) + indent + '    ')}\n"
    )

    # Rebuild the original function minus the extracted part + add new function
    old_func_source = "\n".join(lines[target_lineno - 1:target_end])
    remaining_source = "\n".join(
        textwrap.dedent(ast.unparse(s)) for s in remaining
    )
    new_func_source = (
        f"def {function_name}({', '.join(call_args)}):\n"
        f"{textwrap.indent(remaining_source, '    ')}\n"
        f"    return {call_str}\n"
    )

    new_source = source.replace(old_func_source, new_func_source + "\n" + new_func_def)

    if dry_run:
        return {"success": True, "message": "Preview of extraction", "preview": new_source[:2000]}

    path.write_text(new_source, encoding="utf-8")
    return {
        "success": True,
        "message": f"Extracted {new_function_name} from {function_name}",
    }


async def extract_tool(**kwargs: Any) -> str:
    fp = kwargs.get("file_path", "")
    fn = kwargs.get("function_name", "")
    new_fn = kwargs.get("new_function_name", f"{fn}_part")
    dry = str(kwargs.get("dry_run", "")).lower() in ("true", "1", "yes")
    if not fp or not fn:
        return "Error: file_path, function_name required"
    result = extract_function(fp, fn, new_fn, dry_run=dry)
    if result["success"]:
        if dry:
            return f"[dry-run] Preview:\n{result['preview']}"
        return result["message"]
    return f"Error: {result['error']}"
