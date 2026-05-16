from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


BLOCKED_COMMANDS = [
    "rm -rf /", "rm -rf ~", "rm -rf .", "mkfs", "dd if=", "> /dev/",
    ":(){ :|:& };:", "wget", "curl -O", ":(){ :|:& };:",
    "chmod 777 /", "mv /* ", "fdisk", "format",
]

BLOCKED_PATTERNS = [
    "import shutil; shutil.rmtree",
    "os.remove", "os.unlink", "os.rmdir",
    "subprocess.call", "subprocess.Popen",
    "eval(", "__import__(", "exec(",
]


@dataclass
class SandboxResult:
    stdout: str = ""
    stderr: str = ""
    return_code: int = -1
    duration_ms: float = 0.0
    blocked: bool = False


class SubprocessSandbox:
    """Run Python code in a restricted subprocess. No Docker required."""

    def __init__(self, timeout: int = 30, max_output: int = 100000,
                 allow_imports: list[str] | None = None,
                 blocked_modules: list[str] | None = None):
        self.timeout = timeout
        self.max_output = max_output
        self.allow_imports = allow_imports or ["math", "json", "re", "datetime",
                                                "collections", "itertools", "typing",
                                                "random", "string", "statistics"]
        self.blocked_modules = blocked_modules or ["os", "subprocess", "shutil",
                                                    "socket", "ctypes", "signal",
                                                    "multiprocessing", "threading",
                                                    "importlib", "__import__"]

    def _check_blocked(self, code: str) -> str | None:
        for cmd in BLOCKED_COMMANDS:
            if cmd in code.lower():
                return f"Blocked command: {cmd}"
        for pat in BLOCKED_PATTERNS:
            if pat in code:
                return f"Blocked pattern: {pat}"
        for mod in self.blocked_modules:
            if f"import {mod}" in code or f"from {mod}" in code:
                return f"Blocked module: {mod}"
        return None

    def _build_wrapper(self, code: str) -> str:
        allowed = json.dumps(self.allow_imports)
        return f"""
import sys, math, json as _json, re as _re, datetime as _dt, collections as _collections, itertools as _itertools, typing as _typing, random as _random, string as _string, statistics as _statistics

_allowed_imports = {allowed}

# User code:
{code}
"""

    def run(self, code: str) -> SandboxResult:
        blocked = self._check_blocked(code)
        if blocked:
            return SandboxResult(blocked=True, stderr=blocked)

        wrapped = self._build_wrapper(code)
        start = time.time()

        try:
            result = subprocess.run(
                [sys.executable, "-c", wrapped],
                capture_output=True, text=True,
                timeout=self.timeout,
                env={},  # empty env for isolation
            )
            duration = (time.time() - start) * 1000
            return SandboxResult(
                stdout=result.stdout[:self.max_output],
                stderr=result.stderr[:self.max_output],
                return_code=result.returncode,
                duration_ms=round(duration, 1),
            )
        except subprocess.TimeoutExpired:
            return SandboxResult(stderr=f"Timeout after {self.timeout}s", duration_ms=self.timeout * 1000)
        except Exception as e:
            return SandboxResult(stderr=str(e))

    def run_file(self, file_path: str) -> SandboxResult:
        code = Path(file_path).read_text(encoding="utf-8", errors="ignore")
        return self.run(code)

    def validate(self, code: str) -> dict[str, Any]:
        issues = []
        for mod in self.blocked_modules:
            if f"import {mod}" in code or f"from {mod}" in code:
                issues.append(f"Uses blocked module: {mod}")
        for cmd in BLOCKED_COMMANDS:
            if cmd in code.lower():
                issues.append(f"Contains blocked command pattern")
        return {"safe": len(issues) == 0, "issues": issues}
