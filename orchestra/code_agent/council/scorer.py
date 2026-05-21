from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.council.council import CouncilVerdict

# Task category → keyword signals
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "coding":        ["write", "implement", "create", "function", "class", "algorithm", "generate", "code"],
    "debugging":     ["bug", "fix", "error", "exception", "debug", "issue", "crash", "fail"],
    "refactoring":   ["refactor", "clean", "improve", "optimize", "restructure", "simplify"],
    "analysis":      ["analyze", "review", "audit", "check", "quality", "smell", "assess"],
    "testing":       ["test", "spec", "coverage", "pytest", "unittest", "assert", "mock"],
    "documentation": ["document", "explain", "describe", "comment", "docstring", "readme"],
    "search":        ["find", "search", "locate", "where", "grep", "look for", "discover"],
}

# Dimension weights for reward calculation
_WEIGHTS = {
    "correctness": 0.35,
    "completeness": 0.25,
    "clarity": 0.15,
    "efficiency": 0.15,
    "safety": 0.10,
}


@dataclass
class QualityGateResult:
    verdict: CouncilVerdict
    reward: float               # 0.0–1.0 normalised reward signal
    passed: bool                # did it clear the threshold?
    threshold: float
    weighted_score: float       # weighted mean of dimensions
    task_category: str
    dimension_pass: dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.verdict.agent_name,
            "reward": round(self.reward, 4),
            "passed": self.passed,
            "threshold": self.threshold,
            "weighted_score": round(self.weighted_score, 3),
            "task_category": self.task_category,
            "mean_score": round(self.verdict.mean_score, 3),
            "dimension_pass": self.dimension_pass,
            "council": self.verdict.to_dict(),
        }


class QualityGate:
    """Converts a CouncilVerdict into a reward signal for RL training.

    The gate checks each dimension against its minimum threshold and
    computes a weighted reward in [0, 1].  If the gate fails, reward
    is penalised by a factor so the RL policy learns to avoid poor agents.
    """

    def __init__(
        self,
        pass_threshold: float = 6.0,    # out of 10
        fail_penalty: float = 0.3,      # multiplier applied when gate fails
        dimension_minimums: dict[str, float] | None = None,
    ):
        self._pass_threshold = pass_threshold
        self._fail_penalty = fail_penalty
        self._dimension_minimums = dimension_minimums or {
            "correctness": 5.0,
            "completeness": 4.0,
            "clarity": 4.0,
            "efficiency": 4.0,
            "safety": 7.0,           # safety has a higher floor
        }

    def evaluate(self, verdict: CouncilVerdict, task: str) -> QualityGateResult:
        weighted = sum(
            verdict.scores.get(dim, 5.0) * weight
            for dim, weight in _WEIGHTS.items()
        )

        dim_pass = {
            dim: verdict.scores.get(dim, 5.0) >= minimum
            for dim, minimum in self._dimension_minimums.items()
        }
        passed = verdict.mean_score >= self._pass_threshold and all(dim_pass.values())

        # Reward = normalised weighted score × pass factor
        raw_reward = weighted / 10.0
        reward = raw_reward if passed else raw_reward * self._fail_penalty

        return QualityGateResult(
            verdict=verdict,
            reward=round(min(max(reward, 0.0), 1.0), 4),
            passed=passed,
            threshold=self._pass_threshold,
            weighted_score=round(weighted, 3),
            task_category=categorise_task(task),
            dimension_pass=dim_pass,
        )


def categorise_task(task: str) -> str:
    """Keyword-based task categorisation — returns the best matching category."""
    task_lower = task.lower()
    best_cat = "general"
    best_score = 0

    for cat, keywords in _CATEGORY_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in task_lower)
        if score > best_score:
            best_score = score
            best_cat = cat

    return best_cat
