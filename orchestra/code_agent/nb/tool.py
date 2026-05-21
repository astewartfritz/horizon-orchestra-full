from __future__ import annotations

import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class NbTool(Tool):
    spec = ToolSpec(
        name="jupyter",
        description="Execute Jupyter notebook cells or convert notebooks to/from Python scripts. Requires jupyter in PATH.",
        parameters={
            "action": {
                "type": "string",
                "description": "run (execute notebook), convert (ipynb->py), create (new notebook), read (show contents)",
                "default": "run",
            },
            "path": {"type": "string", "description": "Path to .ipynb file"},
            "code": {"type": "string", "description": "Python code to execute in a new notebook cell", "default": ""},
            "kernel": {"type": "string", "description": "Kernel name", "default": "python3"},
            "timeout": {"type": "integer", "description": "Cell execution timeout seconds", "default": 120},
        },
    )

    async def __call__(
        self,
        action: str = "run",
        path: str = "",
        code: str = "",
        kernel: str = "python3",
        timeout: int = 120,
    ) -> ToolResult:
        try:
            if action == "create":
                nb_path = path or "notebook.ipynb"
                nb = {
                    "nbformat": 4,
                    "nbformat_minor": 5,
                    "cells": [],
                    "metadata": {"kernelspec": {"name": kernel, "display_name": kernel}},
                }
                if code:
                    nb["cells"].append({
                        "cell_type": "code",
                        "source": [code],
                        "metadata": {},
                        "outputs": [],
                        "execution_count": None,
                    })
                Path(nb_path).write_text(json.dumps(nb, indent=2))
                return ToolResult(output=f"Created notebook: {nb_path}")

            elif action == "read":
                nb_path = Path(path)
                if not nb_path.exists():
                    return ToolResult(error=f"Notebook not found: {path}")
                nb = json.loads(nb_path.read_text(encoding="utf-8"))
                lines = [f"Notebook: {path}\n"]
                for i, cell in enumerate(nb.get("cells", [])):
                    ctype = cell.get("cell_type", "code")
                    src = "".join(cell.get("source", []))
                    lines.append(f"[{i}] {ctype}: {src[:200].strip()}")
                return ToolResult(output="\n".join(lines))

            elif action == "convert":
                nb_path = Path(path)
                if not nb_path.exists():
                    return ToolResult(error=f"Notebook not found: {path}")
                py_path = nb_path.with_suffix(".py")
                result = subprocess.run(
                    ["jupyter", "nbconvert", "--to", "script", str(nb_path)],
                    capture_output=True, text=True, timeout=timeout,
                )
                if result.returncode != 0:
                    return ToolResult(error=result.stderr[:2000])
                return ToolResult(output=f"Converted: {py_path}")

            elif action == "run":
                nb_path = Path(path)
                if not nb_path.exists():
                    return ToolResult(error=f"Notebook not found: {path}")
                result = subprocess.run(
                    ["jupyter", "nbconvert", "--to", "notebook",
                     "--execute", "--inplace", str(nb_path)],
                    capture_output=True, text=True, timeout=timeout,
                )
                if result.returncode != 0:
                    return ToolResult(error=result.stderr[:2000])
                return ToolResult(output=f"Executed: {path}")

            else:
                return ToolResult(error=f"Unknown action: {action}")

        except FileNotFoundError:
            return ToolResult(error="jupyter not found in PATH. Install with: pip install jupyter nbconvert")
        except subprocess.TimeoutExpired:
            return ToolResult(error=f"Execution timed out after {timeout}s")
        except Exception as e:
            return ToolResult(error=str(e))
