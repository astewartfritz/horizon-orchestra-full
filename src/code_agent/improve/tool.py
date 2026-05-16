from __future__ import annotations

from code_agent.improve.self_improve import SelfImprover
from code_agent.tools.base import Tool, ToolResult, ToolSpec


class ImproveTool(Tool):
    spec = ToolSpec(
        name="improve",
        description="Analyze and auto-improve Python code files. Can analyze for issues or apply AI-generated fixes.",
        parameters={
            "path": {"type": "string", "description": "File or directory to analyze/improve"},
            "action": {
                "type": "string",
                "description": "analyze (default), improve, or auto (analyze + apply fixes)",
                "default": "analyze",
            },
            "pattern": {"type": "string", "description": "Glob pattern for directories", "default": "**/*.py"},
        },
    )

    async def __call__(self, path: str, action: str = "analyze", pattern: str = "**/*.py") -> ToolResult:
        try:
            improver = SelfImprover()
            from pathlib import Path

            if action == "auto":
                results = await improver.analyze_and_improve(path, auto_apply=True)
            elif action == "improve":
                analysis = await improver.analyze_file(path)
                results = []
                for r in analysis:
                    if not r.error:
                        improved = await improver.improve_file(path, r.suggestion)
                        results.append(improved)
            else:
                results = await improver.analyze_file(path)

            if not results:
                return ToolResult(output="(no suggestions)")

            lines = []
            changes = [r for r in results if r.applied]
            suggestions = [r for r in results if not r.applied]

            if suggestions:
                lines.append(f"Suggestions for {path} ({len(suggestions)} items):")
                for r in suggestions:
                    lines.append(f"  [{r.category}/{r.severity}] {r.suggestion[:200]}")

            if changes:
                lines.append(f"\nApplied changes ({len(changes)} items):")
                for r in changes:
                    if r.diff:
                        lines.append(f"\n{r.diff[:2000]}")
                    if r.error:
                        lines.append(f"  Error: {r.error}")

            return ToolResult(output="\n".join(lines))

        except Exception as e:
            return ToolResult(error=str(e))
