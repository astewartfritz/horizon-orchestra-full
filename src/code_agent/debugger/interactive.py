from __future__ import annotations

import asyncio
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DebuggerFrame:
    filename: str = ""
    lineno: int = 0
    function: str = ""
    code_context: str = ""
    locals: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"filename": self.filename, "lineno": self.lineno,
                "function": self.function, "code_context": self.code_context[:200],
                "locals": {k: str(v)[:100] for k, v in list(self.locals.items())[:10]}}


class InteractiveDebugger:
    """Debug Python code interactively by injecting a breakpoint and stepping through."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout

    def _inject_debugger(self, code: str, breakpoints: list[int]) -> str:
        lines = code.split("\n")
        debug_setup = """
import sys, traceback as _tb

class _SimpleDebugger:
    def __init__(self, breakpoints):
        self.breakpoints = set(breakpoints)
        self.step_count = 0

    def trace(self, frame, event, arg):
        lineno = frame.f_lineno
        filename = frame.f_code.co_filename
        if '<string>' not in filename and '<exec>' not in filename:
            return self.trace
        if event == 'line':
            self.step_count += 1
            if lineno in self.breakpoints:
                locals_copy = {k: repr(v)[:100] for k, v in frame.f_locals.items()}
                print(f'[DEBUG] {frame.f_code.co_name}:{lineno} vars={{{", ".join(f"{k}={v}" for k, v in list(locals_copy.items())[:5])}}}')
        return self.trace

_debugger = _SimpleDebugger({breakpoints})
sys.settrace(_debugger.trace)
""".replace("{breakpoints}", str(breakpoints))

        return debug_setup + "\n" + code

    def debug_code(self, code: str, breakpoints: list[int] | None = None) -> dict[str, Any]:
        bp = breakpoints or []
        wrapped = self._inject_debugger(code, bp)
        start = time.time()

        try:
            result = subprocess.run(
                [sys.executable, "-c", wrapped],
                capture_output=True, text=True, timeout=self.timeout,
            )
            duration = (time.time() - start) * 1000
            debug_lines = [l for l in result.stdout.split("\n") if l.startswith("[DEBUG]")]
            return {
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000],
                "return_code": result.returncode,
                "debug_trace": debug_lines,
                "duration_ms": round(duration, 1),
            }
        except subprocess.TimeoutExpired:
            return {"error": f"Timeout after {self.timeout}s", "debug_trace": []}
        except Exception as e:
            return {"error": str(e), "debug_trace": []}

    def debug_file(self, file_path: str, breakpoints: list[int] | None = None) -> dict[str, Any]:
        code = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        return self.debug_code(code, breakpoints)

    def explain_error(self, error_output: str) -> str:
        explanations = {
            "SyntaxError": "Syntax error: check for missing parentheses, brackets, or quotes.",
            "IndentationError": "Indentation error: check that your code is indented consistently.",
            "NameError": "Name error: a variable or function name is not defined.",
            "TypeError": "Type error: an operation received an argument of unexpected type.",
            "ValueError": "Value error: a function received a valid type but invalid value.",
            "IndexError": "Index error: tried to access a list index that doesn't exist.",
            "KeyError": "Key error: tried to access a dictionary key that doesn't exist.",
            "AttributeError": "Attribute error: object doesn't have the requested attribute.",
            "ImportError": "Import error: a module or import name is not found.",
            "ModuleNotFoundError": "Module not found: install the missing package.",
            "ZeroDivisionError": "Division by zero: check for zero before dividing.",
            "FileNotFoundError": "File not found: check the file path.",
            "RecursionError": "Recursion error: infinite recursion detected.",
        }
        for err_type, explanation in explanations.items():
            if err_type in error_output:
                return f"[{err_type}] {explanation}"
        return f"[Unknown Error] Review the traceback above."
