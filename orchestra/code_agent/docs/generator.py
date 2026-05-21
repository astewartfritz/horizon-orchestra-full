from __future__ import annotations

from pathlib import Path

from orchestra.code_agent.analysis.parser import CodeAnalyzer
from orchestra.code_agent.config import LLMConfig
from orchestra.code_agent.llm.base import LLM, Message
from orchestra.code_agent.tools.base import Tool, ToolResult, ToolSpec


class DocGenerator:
    def __init__(self, llm_config: LLMConfig | None = None):
        self.llm_config = llm_config or LLMConfig(model="gpt-4o-mini")

    async def generate_file_doc(self, file_path: str) -> str:
        p = Path(file_path)
        if not p.exists():
            return f"File not found: {file_path}"
        text = p.read_text("utf-8", errors="replace")
        analyzer = CodeAnalyzer()
        analysis = analyzer.analyze_text(text, file_path)

        summary = (
            f"File: {p.name}\n"
            f"Path: {file_path}\n"
            f"Lines: {analysis.lines_of_code}\n"
            f"Functions: {len(analysis.functions)}\n"
            f"Classes: {len(analysis.classes)}\n"
            f"Imports: {len(analysis.imports)}\n"
        )

        func_details = "\n".join(
            f"- {fn['name']}({', '.join(fn.get('args', []))})"
            for fn in analysis.functions
        )
        class_details = "\n".join(
            f"- {cls['name']}({', '.join(cls.get('bases', []))})"
            f"\n  Methods: {', '.join(cls.get('methods', []))}"
            for cls in analysis.classes
        )

        prompt = (
            f"Generate markdown documentation for this Python file.\n\n"
            f"## Summary\n{summary}\n"
            f"## Functions\n{func_details or '(none)'}\n"
            f"## Classes\n{class_details or '(none)'}\n"
            f"## Source\n```python\n{text[:3000]}\n```\n\n"
            f"Generate comprehensive documentation including: purpose, usage examples, "
            f"parameters, return values, and edge cases. Use markdown headings."
        )

        llm = LLM(
            provider=self.llm_config.provider,
            model=self.llm_config.model,
            api_key=self.llm_config.api_key,
            max_tokens=2000,
            temperature=0.2,
        )

        response = await llm.chat([Message(role="user", content=prompt)])
        return response.content or "(no documentation generated)"

    async def generate_project_readme(self, root_dir: str) -> str:
        root = Path(root_dir)
        py_files = list(root.glob("**/*.py"))

        summary_lines = [f"# {root.name}\n", f"Total Python files: {len(py_files)}\n"]
        for p in py_files[:20]:
            rel = p.relative_to(root)
            analysis = CodeAnalyzer().analyze_file(str(p))
            summary_lines.append(
                f"- `{rel}` ({analysis.lines_of_code} lines, "
                f"{len(analysis.functions)} functions, {len(analysis.classes)} classes)"
            )

        return "\n".join(summary_lines)


class DocGenTool(Tool):
    spec = ToolSpec(
        name="docgen",
        description="Generate markdown documentation for Python files or entire projects using AI analysis.",
        parameters={
            "path": {"type": "string", "description": "File or directory to document"},
            "action": {
                "type": "string",
                "description": "file (default) for single file docs, readme for project overview",
                "default": "file",
            },
        },
    )

    async def __call__(self, path: str, action: str = "file") -> ToolResult:
        try:
            gen = DocGenerator()
            if action == "readme":
                result = await gen.generate_project_readme(path)
            else:
                result = await gen.generate_file_doc(path)
            return ToolResult(output=result[:10000])
        except Exception as e:
            return ToolResult(error=str(e))
