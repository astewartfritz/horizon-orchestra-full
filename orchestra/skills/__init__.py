"""Horizon Orchestra — Horizon Prince Skills.

Composable AI skills: data science, deep research, document generation,
media (image generation + transcription), wide research, web monitoring,
and more. All wired as agent tools.
"""

from .base import Skill, SkillRegistry
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

__all__ = [
    "Skill",
    "SkillRegistry",
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
]
