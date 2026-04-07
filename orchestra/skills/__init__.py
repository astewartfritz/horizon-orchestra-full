"""Horizon Orchestra — Horizon Prince Skills.

Composable AI skills: data science, deep research, document generation,
media (image generation + transcription), wide research, web monitoring,
and more. All wired as agent tools.
"""

from .base import Skill as _BaseSkill, SkillRegistry as _BaseSkillRegistry
from .exploration import DataExplorationSkill
from .statistics import StatisticalAnalysisSkill
from .visualization import VisualizationSkill
from .ml_pipeline import MLPipelineSkill
from .sql_analytics import SQLAnalyticsSkill
from .validation import DataValidationSkill
from .research import DeepResearchSkill
from .documents import DocumentGenerator
from .media import MediaSkill
from .wide_research import WideResearch
from .monitoring import WebMonitor, MonitorScheduler

# Also re-export the richer Skill / SkillRegistry / SkillLoader / SkillActivator
# from orchestra/skills.py (merged upstream module) via importlib to avoid
# the name collision with the skills/ package itself.
import importlib.util as _ilu
import os as _os

import sys as _sys

_skills_py = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "skills.py")
try:
    _pkg_name = "orchestra._skills_full"
    if _pkg_name not in _sys.modules:
        _spec = _ilu.spec_from_file_location(_pkg_name, _skills_py, submodule_search_locations=[])
        _sk_mod = _ilu.module_from_spec(_spec)  # type: ignore[arg-type]
        _sk_mod.__package__ = "orchestra"  # type: ignore[union-attr]
        _sk_mod.__name__ = "orchestra._skills_full"
        _sys.modules[_pkg_name] = _sk_mod
        _spec.loader.exec_module(_sk_mod)  # type: ignore[union-attr]
    else:
        _sk_mod = _sys.modules[_pkg_name]  # type: ignore[assignment]

    Skill = _sk_mod.Skill
    SkillRegistry = _sk_mod.SkillRegistry
    SkillLoader = _sk_mod.SkillLoader
    SkillActivator = _sk_mod.SkillActivator
    SkillMatch = _sk_mod.SkillMatch
    SkillChain = _sk_mod.SkillChain
    BUILTIN_SKILLS = getattr(_sk_mod, "BUILTIN_SKILLS", {})

except Exception as _e:
    import logging as _logging
    _logging.getLogger("orchestra.skills").debug("skills.py not loaded: %s", _e)
    # Fall back to base classes
    Skill = _BaseSkill  # type: ignore[assignment,misc]
    SkillRegistry = _BaseSkillRegistry  # type: ignore[assignment,misc]

    class SkillLoader:  # type: ignore[no-redef]
        """Stub SkillLoader — skills.py not available."""
        @staticmethod
        def validate_name(name: str) -> bool:
            import re
            return bool(re.match(r'^[a-z][a-z0-9-]{0,63}$', name))
        @staticmethod
        def _parse_frontmatter(content: str):
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    import yaml  # type: ignore[import]
                    try:
                        return yaml.safe_load(parts[1]) or {}, parts[2].strip()
                    except Exception:
                        pass
            return {}, content
        def load_from_string(self, content: str, name: str = ""):
            meta, body = self._parse_frontmatter(content)
            s = _BaseSkill.__new__(_BaseSkill)  # type: ignore[abstract]
            return s

    class SkillActivator:  # type: ignore[no-redef]
        """Stub SkillActivator."""
        pass

    BUILTIN_SKILLS: dict = {}


__all__ = [
    # Horizon Prince skill implementations
    "DataExplorationSkill",
    "StatisticalAnalysisSkill",
    "VisualizationSkill",
    "MLPipelineSkill",
    "SQLAnalyticsSkill",
    "DataValidationSkill",
    "DeepResearchSkill",
    "DocumentGenerator",
    "MediaSkill",
    "WideResearch",
    "WebMonitor",
    "MonitorScheduler",
    # Core skill infrastructure
    "Skill",
    "SkillRegistry",
    "SkillLoader",
    "SkillActivator",
    "BUILTIN_SKILLS",
]
