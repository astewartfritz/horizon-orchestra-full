"""Tests for the model council evaluation pipeline."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orchestra.code_agent.council.judge import JudgeScore, LLMJudge, DIMENSIONS
from orchestra.code_agent.council.council import CouncilVerdict, ModelCouncil
from orchestra.code_agent.council.scorer import (
    QualityGate, QualityGateResult, categorise_task, _CATEGORY_KEYWORDS,
)


# ---------------------------------------------------------------------------
# JudgeScore
# ---------------------------------------------------------------------------

class TestJudgeScore:
    def _make(self, **kwargs) -> JudgeScore:
        defaults = dict(
            judge_id="j1", agent_name="a",
            correctness=8.0, completeness=7.0, clarity=7.0,
            efficiency=6.0, safety=9.0,
        )
        return JudgeScore(**{**defaults, **kwargs})

    def test_mean(self):
        s = self._make(correctness=10, completeness=10, clarity=10, efficiency=10, safety=10)
        assert s.mean == pytest.approx(10.0)

    def test_mean_mixed(self):
        s = self._make(correctness=8, completeness=6, clarity=7, efficiency=5, safety=9)
        assert s.mean == pytest.approx(7.0)

    def test_to_dict_has_scores(self):
        s = self._make()
        d = s.to_dict()
        assert "scores" in d
        assert set(d["scores"].keys()) == set(DIMENSIONS)
        assert "mean" in d

    def test_error_field(self):
        s = self._make(error="timeout")
        assert s.error == "timeout"
        assert s.to_dict()["error"] == "timeout"


# ---------------------------------------------------------------------------
# LLMJudge
# ---------------------------------------------------------------------------

class TestLLMJudge:
    def _mock_response(self, scores: dict) -> str:
        return json.dumps({**scores, "reasoning": "looks good"})

    def test_parse_valid_json(self):
        judge = LLMJudge("j1")
        raw = self._mock_response(
            {"correctness": 8, "completeness": 7, "clarity": 9, "efficiency": 7, "safety": 10}
        )
        result = judge._parse(raw, "agent", 100.0)
        assert result.correctness == 8.0
        assert result.safety == 10.0
        assert result.reasoning == "looks good"

    def test_parse_with_surrounding_text(self):
        judge = LLMJudge("j1")
        raw = 'Here is my eval: {"correctness": 7, "completeness": 6, "clarity": 8, "efficiency": 6, "safety": 9, "reasoning": "ok"} Done.'
        result = judge._parse(raw, "agent", 50.0)
        assert result.correctness == 7.0
        assert result.error == ""

    def test_parse_bad_json_returns_neutral(self):
        judge = LLMJudge("j1")
        result = judge._parse("not json at all", "agent", 10.0)
        assert result.error != ""

    def test_evaluate_uses_anthropic_first(self):
        judge = LLMJudge("j1", backend="anthropic")
        good_raw = json.dumps({
            "correctness": 8, "completeness": 8, "clarity": 8,
            "efficiency": 8, "safety": 9, "reasoning": "great"
        })

        async def _run():
            with patch.object(judge, "_try_anthropic", new_callable=AsyncMock, return_value=good_raw):
                return await judge.evaluate("write sort", "def sort(): pass", "codex")

        result = asyncio.run(_run())
        assert result.correctness == 8.0
        assert result.error == ""

    def test_evaluate_falls_back_when_all_fail(self):
        judge = LLMJudge("j1", backend="auto")

        async def _run():
            with patch.object(judge, "_try_anthropic", new_callable=AsyncMock, return_value=None):
                with patch.object(judge, "_try_openai", new_callable=AsyncMock, return_value=None):
                    with patch.object(judge, "_try_ollama", new_callable=AsyncMock, return_value=None):
                        return await judge.evaluate("task", "output", "agent")

        result = asyncio.run(_run())
        # Neutral scores when unavailable
        assert result.mean == pytest.approx(5.0)
        assert result.error == "no backend available"

    def test_evaluate_sets_duration_ms(self):
        judge = LLMJudge("j1", backend="anthropic")
        good_raw = json.dumps({
            "correctness": 5, "completeness": 5, "clarity": 5,
            "efficiency": 5, "safety": 5, "reasoning": "ok"
        })

        async def _run():
            with patch.object(judge, "_try_anthropic", new_callable=AsyncMock, return_value=good_raw):
                return await judge.evaluate("task", "output", "agent")

        result = asyncio.run(_run())
        assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# ModelCouncil
# ---------------------------------------------------------------------------

class TestModelCouncil:
    def _stub_judge(self, judge_id: str, mean: float) -> LLMJudge:
        score = mean  # all dims same for simplicity
        s = JudgeScore(
            judge_id=judge_id, agent_name="agent",
            correctness=score, completeness=score, clarity=score,
            efficiency=score, safety=score,
        )
        j = LLMJudge(judge_id)
        j.evaluate = AsyncMock(return_value=s)
        return j

    def test_evaluate_aggregates_judges(self):
        j1 = self._stub_judge("j1", 8.0)
        j2 = self._stub_judge("j2", 6.0)
        council = ModelCouncil(judges=[j1, j2])

        verdict = asyncio.run(council.evaluate("task", "output", "agent"))
        assert verdict.mean_score == pytest.approx(7.0)
        assert verdict.quorum == 2

    def test_evaluate_single_judge(self):
        j = self._stub_judge("j1", 9.0)
        council = ModelCouncil(judges=[j])

        verdict = asyncio.run(council.evaluate("task", "output", "agent"))
        assert verdict.mean_score == pytest.approx(9.0)
        assert verdict.std_dev == 0.0

    def test_outlier_rejection_with_five_judges(self):
        # With 5 consistent scores and one extreme outlier, the outlier
        # lies >2σ from the mean and gets rejected.
        scores = [
            JudgeScore("j1", "a", 8, 8, 8, 8, 8),
            JudgeScore("j2", "a", 8, 8, 8, 8, 8),
            JudgeScore("j3", "a", 8, 8, 8, 8, 8),
            JudgeScore("j4", "a", 8, 8, 8, 8, 8),
            JudgeScore("j5", "a", 8, 8, 8, 8, 8),
            JudgeScore("j6", "a", 0.1, 0.1, 0.1, 0.1, 0.1),  # extreme outlier
        ]
        council = ModelCouncil(judges=[])
        filtered = council._reject_outliers(scores)
        assert len(filtered) == 5
        assert all(s.judge_id != "j6" for s in filtered)

    def test_outlier_not_rejected_with_only_two_judges(self):
        # With 2 judges, rejection is skipped regardless of values
        scores = [
            JudgeScore("j1", "a", 10, 10, 10, 10, 10),
            JudgeScore("j2", "a", 0, 0, 0, 0, 0),
        ]
        council = ModelCouncil(judges=[])
        filtered = council._reject_outliers(scores)
        assert len(filtered) == 2  # no rejection below threshold

    def test_outlier_rejection_skipped_below_3(self):
        scores = [
            JudgeScore("j1", "a", 8, 8, 8, 8, 8),
            JudgeScore("j2", "a", 2, 2, 2, 2, 2),
        ]
        council = ModelCouncil()
        result = council._reject_outliers(scores)
        assert len(result) == 2  # no rejection with < 3 judges

    def test_verdict_to_dict(self):
        j = self._stub_judge("j1", 7.0)
        council = ModelCouncil(judges=[j])
        verdict = asyncio.run(council.evaluate("task", "output", "agent"))
        d = verdict.to_dict()
        assert "mean_score" in d
        assert "scores" in d
        assert set(d["scores"].keys()) == set(DIMENSIONS)
        assert "judges" in d

    def test_add_remove_judge(self):
        council = ModelCouncil(judges=[])
        j = LLMJudge("new-judge")
        council.add_judge(j)
        assert len(council._judges) == 1
        assert council.remove_judge("new-judge") is True
        assert len(council._judges) == 0

    def test_remove_nonexistent_judge(self):
        council = ModelCouncil(judges=[])
        assert council.remove_judge("ghost") is False


# ---------------------------------------------------------------------------
# categorise_task
# ---------------------------------------------------------------------------

class TestCategoriseTask:
    def test_coding_category(self):
        assert categorise_task("write a function to sort numbers") == "coding"

    def test_debugging_category(self):
        assert categorise_task("fix the bug in the login code") == "debugging"

    def test_refactoring_category(self):
        assert categorise_task("refactor this messy module") == "refactoring"

    def test_testing_category(self):
        assert categorise_task("generate pytest tests for auth module") == "testing"

    def test_documentation_category(self):
        assert categorise_task("write docstrings to explain the API") == "documentation"

    def test_search_category(self):
        assert categorise_task("find where the config is loaded") == "search"

    def test_general_fallback(self):
        assert categorise_task("xyzzy frobnicate the quux") == "general"


# ---------------------------------------------------------------------------
# QualityGate
# ---------------------------------------------------------------------------

class TestQualityGate:
    def _make_verdict(
        self,
        mean: float,
        scores: dict | None = None,
    ) -> CouncilVerdict:
        if scores is None:
            scores = {d: mean for d in DIMENSIONS}
        return CouncilVerdict(
            agent_name="agent",
            scores=scores,
            mean_score=mean,
            std_dev=0.0,
            judge_scores=[],
            quorum=1,
        )

    def test_passing_verdict(self):
        gate = QualityGate(pass_threshold=6.0)
        verdict = self._make_verdict(8.0)
        result = gate.evaluate(verdict, "write a sort function")
        assert result.passed is True
        assert result.reward > 0.5

    def test_failing_verdict_penalised(self):
        gate = QualityGate(pass_threshold=6.0, fail_penalty=0.3)
        verdict = self._make_verdict(3.0)
        result = gate.evaluate(verdict, "write code")
        assert result.passed is False
        assert result.reward < 0.5

    def test_reward_clamped_to_0_1(self):
        gate = QualityGate()
        verdict = self._make_verdict(10.0)
        result = gate.evaluate(verdict, "task")
        assert 0.0 <= result.reward <= 1.0

    def test_safety_minimum_fails_gate(self):
        gate = QualityGate(pass_threshold=6.0)
        # Safety minimum is 7.0 by default — score of 5 should fail
        scores = {d: 8.0 for d in DIMENSIONS}
        scores["safety"] = 5.0
        verdict = self._make_verdict(7.5, scores=scores)
        result = gate.evaluate(verdict, "task")
        assert result.passed is False
        assert result.dimension_pass["safety"] is False

    def test_task_category_set(self):
        gate = QualityGate()
        verdict = self._make_verdict(7.0)
        result = gate.evaluate(verdict, "fix the bug")
        assert result.task_category == "debugging"

    def test_to_dict_complete(self):
        gate = QualityGate()
        verdict = self._make_verdict(7.0)
        result = gate.evaluate(verdict, "test task")
        d = result.to_dict()
        assert "reward" in d
        assert "passed" in d
        assert "council" in d
        assert "dimension_pass" in d
