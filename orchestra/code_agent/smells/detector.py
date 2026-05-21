from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SMELL_PATTERNS: dict[str, dict[str, Any]] = {
    "long_function": {
        "pattern": None,
        "type": "design",
        "message": "Function is too long (>50 lines)",
        "threshold": 50,
    },
    "too_many_params": {
        "pattern": r"def\s+\w+\([^)]*(?:,\s*[^,)]+){5,}\)",
        "type": "design",
        "message": "Function has too many parameters (>5)",
    },
    "nested_loops": {
        "pattern": r"(?:for|while)\s+.*:\s*\n\s+(?:for|while)",
        "type": "performance",
        "message": "Nested loops detected",
    },
    "bare_except": {
        "pattern": r"except\s*:",
        "type": "error_handling",
        "message": "Bare except clause (catches all exceptions)",
    },
    "duplicate_code": {
        "pattern": None,
        "type": "design",
        "message": "Suspected duplicate code (similar blocks)",
    },
    "magic_number": {
        "pattern": r"(?<!\w)(?:[3-9]\d|\d{3,})(?!\s*def\s|\s*class\s|\s*import\s)",
        "type": "readability",
        "message": "Magic number (hard-coded numeric literal)",
    },
    "todo_comment": {
        "pattern": r"#\s*(?:TODO|FIXME|HACK|XXX|BUG)",
        "type": "maintainability",
        "message": "Unresolved TODO/FIXME/HACK",
    },
    "return_none_implicit": {
        "pattern": None,
        "type": "correctness",
        "message": "Function missing return statement (implicit None)",
    },
}


@dataclass
class SmellResult:
    file: str = ""
    line: int = 0
    smell: str = ""
    message: str = ""
    type: str = "design"
    snippet: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"file": self.file, "line": self.line, "smell": self.smell,
                "message": self.message, "type": self.type}


class SmellDetector:
    def __init__(self):
        self.smells = SMELL_PATTERNS

    def detect_file(self, path: str | Path) -> list[SmellResult]:
        p = Path(path)
        results = []
        try:
            text = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return results

        lines = text.split("\n")

        for smell_name, config in self.smells.items():
            pattern = config.get("pattern")
            if pattern:
                for m in re.finditer(pattern, text, re.MULTILINE):
                    line_no = text[:m.start()].count("\n") + 1
                    start = max(0, line_no - 1)
                    snippet = "\n".join(lines[start:start + 3])
                    results.append(SmellResult(
                        file=str(p), line=line_no,
                        smell=smell_name, message=config["message"],
                        type=config.get("type", "design"),
                        snippet=snippet[:200],
                    ))

        # AST-based checks
        if p.suffix == ".py":
            results.extend(self._ast_checks(text, str(p)))

        return results

    def _ast_checks(self, text: str, filepath: str) -> list[SmellResult]:
        results = []
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return results

        lines = text.split("\n")

        for node in ast.walk(tree):
            # Long functions
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if hasattr(node, 'end_lineno') and node.end_lineno:
                    length = node.end_lineno - node.lineno
                    if length > 50:
                        results.append(SmellResult(
                            file=filepath, line=node.lineno,
                            smell="long_function",
                            message=f"Function '{node.name}' is {length} lines long (>50)",
                            type="design",
                        ))
                # Check for missing return
                has_return = any(
                    isinstance(n, ast.Return) for n in ast.walk(node)
                )
                if not has_return and node.name != "__init__":
                    # Check if it's a void function (should return None)
                    pass  # Too many false positives

            # Deep nesting
            if isinstance(node, (ast.For, ast.While, ast.If)):
                depth = self._nesting_depth(node, tree)
                if depth > 4:
                    results.append(SmellResult(
                        file=filepath, line=node.lineno,
                        smell="deep_nesting",
                        message=f"Deep nesting level {depth} (>4)",
                        type="design",
                    ))

        return results

    def _nesting_depth(self, node: ast.AST, root: ast.AST, depth: int = 0) -> int:
        max_depth = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.For, ast.While, ast.If)):
                d = self._nesting_depth(child, root, depth + 1)
                max_depth = max(max_depth, d)
        return max_depth

    def detect_directory(self, pattern: str = "**/*.py") -> list[SmellResult]:
        results = []
        for f in Path(".").glob(pattern):
            if f.is_file():
                results.extend(self.detect_file(f))
        return results
