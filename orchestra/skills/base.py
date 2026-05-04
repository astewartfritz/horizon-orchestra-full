"""Skill base class and registry.

Skills are composable data science capabilities that generate Python code,
execute it in the sandbox, and return structured results.  Following the
Connector pattern from ORCHESTRA.md: each skill registers OpenAI-format tools
into the agent's ToolRegistry.
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
import textwrap
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

__all__ = ["Skill", "SkillRegistry"]

log = logging.getLogger("orchestra.skills")


class Skill(ABC):
    """Base class for all data science skills."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return OpenAI-format tool schemas."""
        ...

    @abstractmethod
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Execute a skill action."""
        ...


async def run_code_in_sandbox(code: str, timeout: int = 60) -> dict[str, Any]:
    """Execute Python code in a subprocess sandbox.

    This is the shared execution engine for all skills — they generate
    code strings and this function runs them, capturing stdout/stderr.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            "python3", tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            return {"error": "Execution timed out", "timeout": timeout}

        stdout_str = stdout.decode(errors="replace")[:50_000]
        stderr_str = stderr.decode(errors="replace")[:10_000]

        # Try to parse stdout as JSON (skills output structured results)
        result: dict[str, Any] = {"exit_code": proc.returncode}
        try:
            parsed = json.loads(stdout_str)
            result["data"] = parsed
        except (json.JSONDecodeError, ValueError):
            result["stdout"] = stdout_str

        if stderr_str.strip():
            result["stderr"] = stderr_str

        return result
    finally:
        Path(tmp_path).unlink(missing_ok=True)


class SkillRegistry:
    """Central registry for data science skills."""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill
        log.info("Registered skill: %s", skill.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def register_tools(self, tool_registry: Any) -> None:
        """Inject all skill tools into an agent ToolRegistry."""
        for skill in self._skills.values():
            for tool_def in skill.get_tool_definitions():
                fn = tool_def.get("function", {})
                tool_name = fn.get("name", "")
                if not tool_name:
                    continue

                _skill = skill
                _action = tool_name

                async def _handler(_s=_skill, _a=_action, **kwargs: Any) -> str:
                    result = await _s.execute(_a, kwargs)
                    return json.dumps(result)

                tool_registry.register(
                    name=tool_name,
                    description=fn.get("description", ""),
                    parameters=fn.get("parameters", {}),
                    handler=_handler,
                )

    def list_skills(self) -> list[dict[str, str]]:
        return [{"name": s.name, "description": s.description} for s in self._skills.values()]

    @classmethod
    def default(cls, router: Any = None) -> "SkillRegistry":
        """Create a registry with all Horizon Prince skills."""
        from .exploration import DataExplorationSkill
        from .statistics import StatisticalAnalysisSkill
        from .visualization import VisualizationSkill
        from .ml_pipeline import MLPipelineSkill
        from .sql_analytics import SQLAnalyticsSkill
        from .validation import DataValidationSkill

        reg = cls()
        # Core data science skills (no router needed)
        reg.register(DataExplorationSkill())
        reg.register(StatisticalAnalysisSkill())
        reg.register(VisualizationSkill())
        reg.register(MLPipelineSkill())
        reg.register(SQLAnalyticsSkill())
        reg.register(DataValidationSkill())

        # Advanced Horizon Prince skills (need router — register if available)
        try:
            from .research import DeepResearchSkill
            reg.register(DeepResearchSkill(router=router))
        except Exception:
                        import logging as _log; _log.getLogger('skills.base').debug('Suppressed exception', exc_info=True)
        try:
            from .documents import DocumentGenerator
            reg.register(DocumentGenerator())
        except Exception:
                        import logging as _log; _log.getLogger('skills.base').debug('Suppressed exception', exc_info=True)
        try:
            from .media import MediaSkill
            reg.register(MediaSkill())
        except Exception:
                        import logging as _log; _log.getLogger('skills.base').debug('Suppressed exception', exc_info=True)
        try:
            from .wide_research import WideResearch
            reg.register(WideResearch(router=router))
        except Exception:
                        import logging as _log; _log.getLogger('skills.base').debug('Suppressed exception', exc_info=True)
        try:
            from .monitoring import WebMonitor
            reg.register(WebMonitor())
        except Exception:
                        import logging as _log; _log.getLogger('skills.base').debug('Suppressed exception', exc_info=True)

        return reg
