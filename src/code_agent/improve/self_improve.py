from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from code_agent.analysis.parser import CodeAnalyzer
from code_agent.config import AgentConfig
from code_agent.llm.base import LLM, Message


@dataclass
class ImprovementResult:
    file_path: str
    suggestion: str
    diff: str
    severity: str = "info"  # info, warning, critical
    category: str = "style"  # style, performance, bug, security, docs
    applied: bool = False
    error: str | None = None


class SelfImprover:
    def __init__(self, agent_config: AgentConfig | None = None):
        self.config = agent_config or AgentConfig(max_iterations=10)
        self.analyzer = CodeAnalyzer()

    async def analyze_file(self, file_path: str) -> list[ImprovementResult]:
        p = Path(file_path)
        if not p.exists():
            return [ImprovementResult(file_path, "", "", error=f"File not found: {file_path}")]

        text = p.read_text("utf-8", errors="replace")
        analysis = self.analyzer.analyze_text(text, file_path)

        llm = LLM(
            provider=self.config.llm.provider,
            model=self.config.llm.model,
            api_key=self.config.llm.api_key,
            max_tokens=2000,
            temperature=0.2,
        )

        analysis_summary = (
            f"File: {file_path}\n"
            f"Lines: {analysis.lines_of_code}\n"
            f"Functions: {len(analysis.functions)}\n"
            f"Classes: {len(analysis.classes)}\n"
            f"Imports: {len(analysis.imports)}\n"
        )

        prompt = (
            f"Review this Python file and suggest improvements. "
            f"Focus on: bugs, security issues, performance, code style, and documentation.\n\n"
            f"{analysis_summary}\n```python\n{text[:4000]}\n```\n\n"
            f"For each suggestion, provide: category (bug/security/performance/style/docs), "
            f"severity (critical/warning/info), the issue, and the fix."
        )

        messages = [
            Message(role="system", content="You are an expert code reviewer. Analyze and suggest specific improvements."),
            Message(role="user", content=prompt),
        ]

        response = await llm.chat(messages)
        content = response.content or ""
        result = ImprovementResult(
            file_path=file_path,
            suggestion=content,
            diff="",
            severity="info",
            category="style",
        )
        return [result]

    async def improve_file(self, file_path: str, suggestion: str) -> ImprovementResult:
        p = Path(file_path)
        text = p.read_text("utf-8", errors="replace")

        llm = LLM(
            provider=self.config.llm.provider,
            model=self.config.llm.model,
            api_key=self.config.llm.api_key,
            max_tokens=4000,
            temperature=0.1,
        )

        prompt = (
            f"Apply the following improvement suggestions to this file.\n\n"
            f"Suggestions:\n{suggestion}\n\n"
            f"Current file:\n```python\n{text}\n```\n\n"
            f"Respond with ONLY the complete improved code, wrapped in ```python ... ```"
        )

        messages = [
            Message(role="system", content="You apply code improvements. Return only the improved code."),
            Message(role="user", content=prompt),
        ]

        response = await llm.chat(messages)
        content = response.content or ""

        import re
        match = re.search(r"```python\n(.*?)```", content, re.DOTALL)
        if not match:
            match = re.search(r"```\n(.*?)```", content, re.DOTALL)
        if not match:
            return ImprovementResult(
                file_path=file_path, suggestion=suggestion, diff="",
                error="Could not extract code from response"
            )

        new_code = match.group(1).strip()
        diff = "".join(difflib.unified_diff(
            text.splitlines(keepends=True),
            new_code.splitlines(keepends=True),
            fromfile=file_path, tofile=file_path,
        ))

        if not diff.strip():
            return ImprovementResult(
                file_path=file_path, suggestion=suggestion, diff=diff,
                error="No changes generated"
            )

        p.write_text(new_code, "utf-8")
        return ImprovementResult(
            file_path=file_path, suggestion=suggestion, diff=diff,
            severity="info", category="improvement", applied=True,
        )

    async def analyze_and_improve(self, file_path: str, auto_apply: bool = False) -> list[ImprovementResult]:
        results = await self.analyze_file(file_path)
        if auto_apply:
            for r in results:
                if not r.error:
                    improved = await self.improve_file(file_path, r.suggestion)
                    results.append(improved)
        return results

    async def improve_project(self, root_dir: str, pattern: str = "src/**/*.py", auto_apply: bool = False) -> dict[str, list[ImprovementResult]]:
        root = Path(root_dir)
        all_results: dict[str, list[ImprovementResult]] = {}
        for p in root.glob(pattern):
            results = await self.analyze_and_improve(str(p), auto_apply=auto_apply)
            all_results[str(p)] = results
        return all_results
