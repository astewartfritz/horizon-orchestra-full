"""Horizon Orchestra Red Team — continuous adversarial security evaluation.

Provides a full-stack red-team system with 500+ attack payloads, a
genetic-algorithm mutation engine, chaos-engineering orchestrator, and
an automated hardening advisor.

Components
----------
- ``attack_vectors``      — 500+ payloads across 10 attack classes
- ``mutation_engine``     — Genetic-algorithm payload evolution
- ``chaos_orchestrator``  — Infrastructure fault injection & MTTR
- ``red_team_runner``     — Full-suite orchestrator with grading
- ``hardening_advisor``   — Auto-generates security patches from bypasses
"""

from __future__ import annotations

from .attack_vectors import ATTACK_PAYLOADS, AttackClass, AttackPayload
from .mutation_engine import MutatedPayload, MutationEngine, MutationType
from .chaos_orchestrator import (
    ChaosCategory,
    ChaosOrchestrator,
    ChaosReport,
    ChaosResult,
    ChaosScenario,
)
from .red_team_runner import (
    BenchmarkReport,
    BypassFinding,
    ClassResult,
    RedTeamReport,
    RedTeamRunner,
)
from .hardening_advisor import (
    AppliedPatch,
    HardeningAdvisor,
    HardeningPatch,
    RegressionReport,
    SecurityRule,
)

__all__ = [
    # attack_vectors
    "ATTACK_PAYLOADS",
    "AttackClass",
    "AttackPayload",
    # mutation_engine
    "MutatedPayload",
    "MutationEngine",
    "MutationType",
    # chaos_orchestrator
    "ChaosCategory",
    "ChaosOrchestrator",
    "ChaosReport",
    "ChaosResult",
    "ChaosScenario",
    # red_team_runner
    "BenchmarkReport",
    "BypassFinding",
    "ClassResult",
    "RedTeamReport",
    "RedTeamRunner",
    # hardening_advisor
    "AppliedPatch",
    "HardeningAdvisor",
    "HardeningPatch",
    "RegressionReport",
    "SecurityRule",
]
