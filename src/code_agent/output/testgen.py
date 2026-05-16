from __future__ import annotations

import ast
from pathlib import Path

from code_agent.analysis.parser import CodeAnalyzer
from code_agent.tools.base import Tool, ToolResult, ToolSpec


class TestGenerator:
    def generate(self, file_path: str, framework: str = "pytest") -> str:
        p = Path(file_path)
        if not p.exists():
            return f"# File not found: {file_path}"

        text = p.read_text("utf-8", errors="replace")
        analysis = CodeAnalyzer().analyze_text(text, filename=file_path)

        if framework == "pytest":
            return self._generate_pytest(file_path, analysis)
        elif framework == "unittest":
            return self._generate_unittest(file_path, analysis)
        else:
            return f"# Unsupported framework: {framework}"

    def _generate_pytest(self, file_path: str, analysis) -> str:
        import_name = Path(file_path).stem
        lines = [
            f"\"\"\"Tests for {file_path}\"\"\"",
            "import pytest",
            f"from {import_name} import (",
        ]

        names_to_import = []
        for fn in analysis.functions:
            if not fn["name"].startswith("_"):
                names_to_import.append(f"    {fn['name']},")
        for cls in analysis.classes:
            names_to_import.append(f"    {cls['name']},")

        if names_to_import:
            lines.extend(names_to_import)
            lines.append(")")

        lines.append("")

        for fn in analysis.functions:
            if fn["name"].startswith("_"):
                continue
            lines.append(f"def test_{fn['name']}():")
            lines.append(f"    \"\"\"Test {fn['name']}.\"\"\"")
            args = fn.get("args", [])
            if args:
                fixtures = ", ".join(args)
                lines.append(f"    result = {fn['name']}({fixtures})")
            else:
                lines.append(f"    result = {fn['name']}()")
            lines.append(f"    assert result is not None")
            lines.append("")

        for cls in analysis.classes:
            lines.append(f"class Test{cls['name']}:")
            for method in cls.get("methods", []):
                if method.startswith("_"):
                    continue
                lines.append(f"    def test_{method}(self):")
                lines.append(f"        \"\"\"Test {cls['name']}.{method}.\"\"\"")
                lines.append(f"        instance = {cls['name']}()")
                lines.append(f"        result = instance.{method}()")
                lines.append(f"        assert result is not None")
                lines.append("")

        return "\n".join(lines)

    def _generate_unittest(self, file_path: str, analysis) -> str:
        import_name = Path(file_path).stem
        lines = [
            f"\"\"\"Tests for {file_path}\"\"\"",
            "import unittest",
            f"from {import_name} import *",
            "",
            "",
        ]

        for fn in analysis.functions:
            if fn["name"].startswith("_"):
                continue
            lines.append(f"    def test_{fn['name']}(self):")
            lines.append(f"        \"\"\"Test {fn['name']}.\"\"\"")
            lines.append(f"        result = {fn['name']}()")
            lines.append(f"        self.assertIsNotNone(result)")
            lines.append("")

        if any(not f["name"].startswith("_") for f in analysis.functions):
            lines.insert(3, f"class TestFunctions(unittest.TestCase):")

        return "\n".join(lines)


class TestGenTool(Tool):
    spec = ToolSpec(
        name="testgen",
        description="Auto-generate test files from source code using AST analysis.",
        parameters={
            "file_path": {"type": "string", "description": "Source file to generate tests for"},
            "framework": {"type": "string", "description": "Test framework: pytest (default) or unittest", "default": "pytest"},
            "output": {"type": "string", "description": "Output path (default: tests/test_<name>.py)"},
        },
    )

    async def __call__(self, file_path: str, framework: str = "pytest", output: str = "") -> ToolResult:
        try:
            gen = TestGenerator()
            test_code = gen.generate(file_path, framework)

            if output:
                out_path = Path(output)
            else:
                name = Path(file_path).stem
                out_path = Path("tests") / f"test_{name}.py"

            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(test_code, "utf-8")

            return ToolResult(
                output=f"Generated tests for {file_path} -> {out_path}\n{test_code[:2000]}"
            )
        except Exception as e:
            return ToolResult(error=str(e))
