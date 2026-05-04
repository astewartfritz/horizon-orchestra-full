"""Horizon Orchestra — Evaluation Engine.

Agent-as-Judge: uses a separate LLM call to score agent outputs on
multiple dimensions.  Quality gates that can block or retry low-quality
results.  Based on the Agent-as-a-Judge paper (arXiv:2601.05111).

Usage::

    from orchestra.evaluation import Evaluator, QualityGate
    evaluator = Evaluator(router)
    score = await evaluator.evaluate(task="Build an API", output="...", criteria=["correctness", "completeness"])
    gate = QualityGate(min_score=0.7)
    gate.check(score)  # raises if below threshold
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from .router import ModelRouter

__all__ = [
    "Evaluator",
    "EvalResult",
    "QualityGate",
    "EvalCriteria",
    "CRITERIA_LIBRARY",
]

log = logging.getLogger("orchestra.evaluation")


# ---------------------------------------------------------------------------
# Criteria library
# ---------------------------------------------------------------------------

CRITERIA_LIBRARY: dict[str, str] = {
    "correctness": "Is the output factually correct and free of errors? Does it accurately address the task?",
    "completeness": "Does the output fully address all parts of the task? Are there any missing elements?",
    "relevance": "Is the output relevant to the task? Does it stay on topic without unnecessary tangents?",
    "clarity": "Is the output clear, well-organized, and easy to understand?",
    "code_quality": "If code is present: is it production-quality, well-structured, handles errors, and follows best practices?",
    "reasoning": "Does the output demonstrate sound reasoning? Are conclusions logically supported?",
    "creativity": "Does the output show creative problem-solving or novel approaches where appropriate?",
    "safety": "Is the output safe? Does it avoid harmful, biased, or dangerous content?",
    "efficiency": "Was the task solved efficiently? Minimal unnecessary steps or tool calls?",
    "citation_quality": "Are sources cited? Are citations accurate and from reliable sources?",
}


@dataclass
class EvalCriteria:
    name: str
    description: str
    weight: float = 1.0


@dataclass
class CriterionScore:
    name: str
    score: float           # 0.0 to 1.0
    reasoning: str = ""
    weight: float = 1.0


@dataclass
class EvalResult:
    """Result of evaluating an agent's output."""
    overall_score: float                        # 0.0 to 1.0
    grade: str                                  # A, B, C, D, F
    criteria_scores: list[CriterionScore] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    model_used: str = ""
    eval_duration: float = 0.0
    passed_gate: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_score": self.overall_score,
            "grade": self.grade,
            "criteria": [
                {"name": c.name, "score": c.score, "reasoning": c.reasoning}
                for c in self.criteria_scores
            ],
            "strengths": self.strengths,
            "weaknesses": self.weaknesses,
            "suggestions": self.suggestions,
            "model": self.model_used,
            "duration": self.eval_duration,
            "passed": self.passed_gate,
        }


# ---------------------------------------------------------------------------
# Evaluation prompt
# ---------------------------------------------------------------------------

EVAL_SYSTEM = """\
You are an expert evaluator in Horizon Orchestra. Your job is to
rigorously assess an agent's output against specific criteria.

For each criterion, provide:
- A score from 0.0 (terrible) to 1.0 (perfect)
- A brief reasoning (1-2 sentences)

Then provide:
- Overall strengths (list)
- Overall weaknesses (list)
- Specific improvement suggestions (list)

Respond with a JSON object:
{
  "criteria": [
    {"name": "criterion_name", "score": 0.85, "reasoning": "..."}
  ],
  "strengths": ["..."],
  "weaknesses": ["..."],
  "suggestions": ["..."]
}

Be rigorous. A score of 0.7 means "acceptable but needs improvement".
A score of 0.9+ means "excellent, production-ready".
Do not inflate scores.
"""

EVAL_USER = """\
Task given to the agent:
{task}

Agent's output:
{output}

Evaluate on these criteria:
{criteria_block}

Provide your evaluation as JSON.
"""


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class Evaluator:
    """Agent-as-Judge evaluation engine."""

    def __init__(
        self,
        router: ModelRouter | None = None,
        judge_model: str = "kimi-k2.5",
    ) -> None:
        self.router = router or ModelRouter()
        self.judge_model = judge_model

    async def evaluate(
        self,
        task: str,
        output: str,
        criteria: list[str] | None = None,
        custom_criteria: list[EvalCriteria] | None = None,
    ) -> EvalResult:
        """Evaluate an agent's output.

        *criteria* is a list of names from CRITERIA_LIBRARY.
        *custom_criteria* can add domain-specific evaluation dimensions.
        """
        t0 = time.monotonic()

        # Build criteria list
        eval_criteria: list[EvalCriteria] = []
        for name in (criteria or ["correctness", "completeness", "clarity"]):
            desc = CRITERIA_LIBRARY.get(name, name)
            eval_criteria.append(EvalCriteria(name=name, description=desc))
        if custom_criteria:
            eval_criteria.extend(custom_criteria)

        criteria_block = "\n".join(
            f"- {c.name} (weight {c.weight}): {c.description}"
            for c in eval_criteria
        )

        user_prompt = EVAL_USER.format(
            task=task[:3000],
            output=output[:8000],
            criteria_block=criteria_block,
        )

        # Call the judge model
        client, model_id = self.router.get_client(self.judge_model)
        try:
            resp = await client.chat.completions.create(
                model=model_id,
                messages=[
                    {"role": "system", "content": EVAL_SYSTEM},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
                max_tokens=2048,
            )
            raw = resp.choices[0].message.content or "{}"
            data = json.loads(raw)
        except Exception as exc:
            log.error("Evaluation failed: %s", exc)
            return EvalResult(
                overall_score=0.0, grade="F",
                weaknesses=[f"Evaluation failed: {exc}"],
                model_used=self.judge_model,
                eval_duration=time.monotonic() - t0,
            )

        # Parse scores
        criterion_scores: list[CriterionScore] = []
        weight_map = {c.name: c.weight for c in eval_criteria}

        for item in data.get("criteria", []):
            name = item.get("name", "")
            score = max(0.0, min(1.0, float(item.get("score", 0))))
            criterion_scores.append(CriterionScore(
                name=name,
                score=score,
                reasoning=item.get("reasoning", ""),
                weight=weight_map.get(name, 1.0),
            ))

        # Weighted average
        total_weight = sum(c.weight for c in criterion_scores) or 1.0
        overall = sum(c.score * c.weight for c in criterion_scores) / total_weight

        # Grade
        if overall >= 0.9:
            grade = "A"
        elif overall >= 0.8:
            grade = "B"
        elif overall >= 0.7:
            grade = "C"
        elif overall >= 0.5:
            grade = "D"
        else:
            grade = "F"

        return EvalResult(
            overall_score=round(overall, 3),
            grade=grade,
            criteria_scores=criterion_scores,
            strengths=data.get("strengths", []),
            weaknesses=data.get("weaknesses", []),
            suggestions=data.get("suggestions", []),
            model_used=self.judge_model,
            eval_duration=round(time.monotonic() - t0, 2),
        )

    async def compare(
        self,
        task: str,
        outputs: dict[str, str],
        criteria: list[str] | None = None,
    ) -> dict[str, EvalResult]:
        """Evaluate multiple outputs for the same task and compare."""
        import asyncio
        coros = {
            name: self.evaluate(task, output, criteria)
            for name, output in outputs.items()
        }
        keys = list(coros.keys())
        results_list = await asyncio.gather(*coros.values())
        return dict(zip(keys, results_list))


# ---------------------------------------------------------------------------
# Quality gates
# ---------------------------------------------------------------------------

class QualityGate:
    """Gate that blocks low-quality outputs.

    Use in agent loops to trigger retries or escalation when output
    quality falls below thresholds.
    """

    def __init__(
        self,
        min_score: float = 0.7,
        min_criteria: dict[str, float] | None = None,
        max_retries: int = 2,
    ) -> None:
        self.min_score = min_score
        self.min_criteria = min_criteria or {}
        self.max_retries = max_retries

    def check(self, result: EvalResult) -> EvalResult:
        """Check if the result passes the gate. Sets passed_gate flag."""
        passed = True

        if result.overall_score < self.min_score:
            passed = False

        for cs in result.criteria_scores:
            threshold = self.min_criteria.get(cs.name)
            if threshold and cs.score < threshold:
                passed = False
                break

        result.passed_gate = passed
        return result

    async def evaluate_and_gate(
        self,
        evaluator: Evaluator,
        task: str,
        output: str,
        criteria: list[str] | None = None,
    ) -> EvalResult:
        """Convenience: evaluate + check gate in one call."""
        result = await evaluator.evaluate(task, output, criteria)
        return self.check(result)
