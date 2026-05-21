from __future__ import annotations

import asyncio
import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.council.judge import DIMENSIONS, JudgeScore, LLMJudge

logger = logging.getLogger(__name__)


@dataclass
class CouncilVerdict:
    agent_name: str
    scores: dict[str, float]        # dimension → mean score across judges
    mean_score: float                # overall mean (0–10)
    std_dev: float                   # inter-judge disagreement
    judge_scores: list[JudgeScore]  # raw per-judge scores
    duration_ms: float = 0.0
    quorum: int = 0                  # number of judges that responded

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "scores": {k: round(v, 3) for k, v in self.scores.items()},
            "mean_score": round(self.mean_score, 3),
            "std_dev": round(self.std_dev, 3),
            "quorum": self.quorum,
            "duration_ms": round(self.duration_ms, 1),
            "judges": [j.to_dict() for j in self.judge_scores],
        }


class ModelCouncil:
    """Runs multiple LLM judges concurrently and aggregates their verdicts.

    Outlier rejection: if a judge's mean deviates >2σ from the group mean,
    it is excluded from the final aggregate (requires ≥3 judges).
    """

    def __init__(
        self,
        judges: list[LLMJudge] | None = None,
        min_quorum: int = 1,
    ):
        self._judges = judges if judges is not None else self._default_judges()
        self._min_quorum = min_quorum

    @staticmethod
    def _default_judges() -> list[LLMJudge]:
        return [
            LLMJudge("judge-anthropic", backend="anthropic"),
            LLMJudge("judge-ollama", backend="ollama"),
            LLMJudge("judge-openai", backend="openai"),
        ]

    async def evaluate(
        self,
        task: str,
        output: str,
        agent_name: str,
    ) -> CouncilVerdict:
        start = time.time()

        raw_scores: list[JudgeScore] = await asyncio.gather(
            *[j.evaluate(task, output, agent_name) for j in self._judges],
            return_exceptions=False,
        )

        # Filter out hard errors (error field set, no useful data)
        valid = [s for s in raw_scores if not s.error or s.mean != 5.0]
        if not valid:
            valid = list(raw_scores)  # keep all even if errored

        valid = self._reject_outliers(valid)

        if not valid:
            valid = list(raw_scores)

        dim_scores: dict[str, float] = {}
        for dim in DIMENSIONS:
            vals = [getattr(s, dim) for s in valid]
            dim_scores[dim] = statistics.mean(vals) if vals else 5.0

        means = [s.mean for s in valid]
        overall_mean = statistics.mean(means) if means else 5.0
        std_dev = statistics.stdev(means) if len(means) > 1 else 0.0

        return CouncilVerdict(
            agent_name=agent_name,
            scores=dim_scores,
            mean_score=overall_mean,
            std_dev=std_dev,
            judge_scores=raw_scores,
            duration_ms=(time.time() - start) * 1000,
            quorum=len(valid),
        )

    def _reject_outliers(self, scores: list[JudgeScore]) -> list[JudgeScore]:
        if len(scores) < 3:
            return scores
        means = [s.mean for s in scores]
        mu = statistics.mean(means)
        sigma = statistics.stdev(means)
        if sigma == 0:
            return scores
        return [s for s in scores if abs(s.mean - mu) <= 2 * sigma]

    def add_judge(self, judge: LLMJudge) -> None:
        self._judges.append(judge)

    def remove_judge(self, judge_id: str) -> bool:
        before = len(self._judges)
        self._judges = [j for j in self._judges if j.judge_id != judge_id]
        return len(self._judges) < before
