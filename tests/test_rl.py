"""Tests for the RL pipeline: signals, buffer, policy, trainer, feedback loop."""
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from code_agent.council.council import CouncilVerdict
from code_agent.council.scorer import QualityGateResult
from code_agent.rl.signal import TrainingSignal
from code_agent.rl.buffer import ExperienceBuffer
from code_agent.rl.policy import RoutingPolicy
from code_agent.rl.trainer import OrchestraTrainer, TrainingReport
from code_agent.rl.loop import FeedbackLoop


# ---------------------------------------------------------------------------
# TrainingSignal
# ---------------------------------------------------------------------------

class TestTrainingSignal:
    def test_task_preview_truncated(self):
        s = TrainingSignal(
            task="x" * 200, agent_name="a", task_category="coding",
            reward=0.8, council_mean=8.0, dimension_scores={}, passed_gate=True,
        )
        assert len(s.task_preview) == 100

    def test_to_dict(self):
        s = TrainingSignal(
            task="write sort", agent_name="claude_code", task_category="coding",
            reward=0.85, council_mean=8.5, dimension_scores={"correctness": 9.0},
            passed_gate=True,
        )
        d = s.to_dict()
        assert d["agent_name"] == "claude_code"
        assert d["reward"] == pytest.approx(0.85)
        assert d["passed_gate"] is True


# ---------------------------------------------------------------------------
# ExperienceBuffer
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_buffer(tmp_path):
    return ExperienceBuffer(db_path=str(tmp_path / "test_exp.db"))


def _signal(agent="agent_a", category="coding", reward=0.7, passed=True) -> TrainingSignal:
    return TrainingSignal(
        task="write a sort function",
        agent_name=agent,
        task_category=category,
        reward=reward,
        council_mean=reward * 10,
        dimension_scores={"correctness": reward * 10},
        passed_gate=passed,
    )


class TestExperienceBuffer:
    def test_add_and_recent(self, tmp_buffer):
        tmp_buffer.add(_signal("agent_a", reward=0.8))
        tmp_buffer.add(_signal("agent_b", reward=0.6))
        recent = tmp_buffer.recent(limit=10)
        assert len(recent) == 2

    def test_recent_order(self, tmp_buffer):
        tmp_buffer.add(_signal("agent_a", reward=0.5))
        time.sleep(0.01)
        tmp_buffer.add(_signal("agent_b", reward=0.9))
        recent = tmp_buffer.recent(limit=2)
        # Most recent first
        assert recent[0]["agent_name"] == "agent_b"

    def test_for_agent(self, tmp_buffer):
        tmp_buffer.add(_signal("agent_a"))
        tmp_buffer.add(_signal("agent_b"))
        tmp_buffer.add(_signal("agent_a"))
        rows = tmp_buffer.for_agent("agent_a")
        assert len(rows) == 2
        assert all(r["agent_name"] == "agent_a" for r in rows)

    def test_for_category(self, tmp_buffer):
        tmp_buffer.add(_signal(category="coding"))
        tmp_buffer.add(_signal(category="debugging"))
        rows = tmp_buffer.for_category("coding")
        assert len(rows) == 1

    def test_stats(self, tmp_buffer):
        tmp_buffer.add(_signal("agent_a", reward=0.8, passed=True))
        tmp_buffer.add(_signal("agent_a", reward=0.4, passed=False))
        tmp_buffer.add(_signal("agent_b", reward=0.9, passed=True))
        s = tmp_buffer.stats()
        assert s["total_signals"] == 3
        assert len(s["by_agent"]) == 2
        assert len(s["by_category"]) >= 1

    def test_preference_pairs(self, tmp_buffer):
        # agent_a should win vs agent_b for same category
        tmp_buffer.add(_signal("agent_a", category="coding", reward=0.9))
        tmp_buffer.add(_signal("agent_b", category="coding", reward=0.5))
        pairs = tmp_buffer.preference_pairs(min_reward_gap=0.2)
        assert len(pairs) >= 1
        assert pairs[0]["winner"] == "agent_a"
        assert pairs[0]["loser"] == "agent_b"

    def test_preference_pairs_gap_too_small(self, tmp_buffer):
        tmp_buffer.add(_signal("agent_a", category="coding", reward=0.7))
        tmp_buffer.add(_signal("agent_b", category="coding", reward=0.65))
        pairs = tmp_buffer.preference_pairs(min_reward_gap=0.2)
        assert len(pairs) == 0

    def test_clear_all(self, tmp_buffer):
        tmp_buffer.add(_signal())
        tmp_buffer.add(_signal())
        deleted = tmp_buffer.clear()
        assert deleted == 2
        assert tmp_buffer.recent() == []

    def test_clear_before_timestamp(self, tmp_buffer):
        tmp_buffer.add(_signal())
        ts = time.time()
        time.sleep(0.01)
        tmp_buffer.add(_signal())
        deleted = tmp_buffer.clear(before_timestamp=ts)
        assert deleted == 1
        assert len(tmp_buffer.recent()) == 1

    def test_dimensions_serialized_and_deserialized(self, tmp_buffer):
        s = _signal()
        s.dimension_scores = {"correctness": 8.5, "safety": 9.0}
        tmp_buffer.add(s)
        rows = tmp_buffer.recent(1)
        assert rows[0]["dimensions"]["correctness"] == pytest.approx(8.5)


# ---------------------------------------------------------------------------
# RoutingPolicy
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_policy(tmp_path):
    return RoutingPolicy(db_path=str(tmp_path / "test_policy.db"))


class TestRoutingPolicy:
    def test_first_update_sets_reward(self, tmp_policy):
        ema = tmp_policy.update("claude_code", "coding", 0.9)
        assert ema == pytest.approx(0.9)

    def test_ema_update_pulls_toward_new_reward(self, tmp_policy):
        tmp_policy.update("agent", "coding", 0.0)
        # Multiple updates toward 1.0 should raise EMA
        for _ in range(20):
            ema = tmp_policy.update("agent", "coding", 1.0)
        assert ema > 0.5

    def test_get_ema_returns_default_for_unknown(self, tmp_policy):
        ema = tmp_policy.get_ema("ghost", "unknown_cat")
        assert ema == pytest.approx(0.5)

    def test_priority_boost_high_reward(self, tmp_policy):
        tmp_policy.update("agent", "coding", 1.0)
        boost = tmp_policy.priority_boost("agent", "coding")
        assert boost < 0  # high reward → higher priority → negative boost

    def test_priority_boost_low_reward(self, tmp_policy):
        tmp_policy.update("agent", "coding", 0.0)
        boost = tmp_policy.priority_boost("agent", "coding")
        assert boost > 0  # low reward → lower priority → positive boost

    def test_priority_boost_neutral_at_default(self, tmp_policy):
        boost = tmp_policy.priority_boost("new_agent", "coding")
        assert boost == pytest.approx(0.0)

    def test_agent_rankings(self, tmp_policy):
        tmp_policy.update("agent_a", "coding", 0.9)
        tmp_policy.update("agent_b", "coding", 0.4)
        rankings = tmp_policy.agent_rankings("coding")
        assert rankings[0]["agent_name"] == "agent_a"
        assert rankings[1]["agent_name"] == "agent_b"

    def test_all_entries(self, tmp_policy):
        tmp_policy.update("a1", "coding", 0.8)
        tmp_policy.update("a2", "debugging", 0.6)
        entries = tmp_policy.all_entries()
        assert len(entries) == 2

    def test_reset_agent(self, tmp_policy):
        tmp_policy.update("agent", "coding", 0.9)
        count = tmp_policy.reset_agent("agent")
        assert count == 1
        assert tmp_policy.get_ema("agent", "coding") == pytest.approx(0.5)

    def test_reset_all(self, tmp_policy):
        tmp_policy.update("a", "coding", 0.9)
        tmp_policy.update("b", "testing", 0.7)
        count = tmp_policy.reset_all()
        assert count == 2
        assert tmp_policy.all_entries() == []

    def test_summary(self, tmp_policy):
        tmp_policy.update("best", "coding", 0.95)
        tmp_policy.update("ok", "coding", 0.6)
        s = tmp_policy.summary()
        assert s["total_entries"] == 2
        assert s["top_performers"][0]["agent_name"] == "best"

    def test_warm_start_alpha(self, tmp_policy):
        # First update should set EMA directly to reward (not from 0.5)
        ema = tmp_policy.update("agent", "coding", 0.9)
        assert ema == pytest.approx(0.9)


# ---------------------------------------------------------------------------
# OrchestraTrainer
# ---------------------------------------------------------------------------

class TestOrchestraTrainer:
    def test_train_updates_policy(self, tmp_path):
        buf = ExperienceBuffer(str(tmp_path / "buf.db"))
        pol = RoutingPolicy(str(tmp_path / "pol.db"))
        trainer = OrchestraTrainer(buf, pol)

        buf.add(_signal("agent_a", reward=0.9))
        buf.add(_signal("agent_b", reward=0.3))
        report = trainer.train(run_lora=False)

        assert report.policy_updates == 2
        assert report.lora_trained is False

    def test_train_counts_preference_pairs(self, tmp_path):
        buf = ExperienceBuffer(str(tmp_path / "buf.db"))
        pol = RoutingPolicy(str(tmp_path / "pol.db"))
        trainer = OrchestraTrainer(buf, pol)

        buf.add(_signal("agent_a", reward=0.9))
        buf.add(_signal("agent_b", reward=0.4))
        report = trainer.train()
        # winner gap = 0.5 > default 0.15 → 1 pair
        assert report.preference_pairs >= 1

    def test_lora_skipped_without_transformers(self, tmp_path):
        buf = ExperienceBuffer(str(tmp_path / "buf.db"))
        pol = RoutingPolicy(str(tmp_path / "pol.db"))
        trainer = OrchestraTrainer(buf, pol, min_pairs_for_lora=1)

        buf.add(_signal("agent_a", reward=0.9))
        buf.add(_signal("agent_b", reward=0.4))

        with patch.dict("sys.modules", {"transformers": None, "peft": None}):
            report = trainer.train(run_lora=True)
        assert report.lora_trained is False

    def test_last_reports(self, tmp_path):
        buf = ExperienceBuffer(str(tmp_path / "buf.db"))
        pol = RoutingPolicy(str(tmp_path / "pol.db"))
        trainer = OrchestraTrainer(buf, pol)
        trainer.train()
        trainer.train()
        reports = trainer.last_reports(5)
        assert len(reports) == 2
        assert "policy_updates" in reports[0]

    def test_report_to_dict(self, tmp_path):
        buf = ExperienceBuffer(str(tmp_path / "buf.db"))
        pol = RoutingPolicy(str(tmp_path / "pol.db"))
        trainer = OrchestraTrainer(buf, pol)
        report = trainer.train()
        d = report.to_dict()
        assert "duration_ms" in d
        assert "lora_trained" in d


# ---------------------------------------------------------------------------
# FeedbackLoop
# ---------------------------------------------------------------------------

def _make_dispatch_record(task="write sort", agent="claude_code", output="def sort(): pass", success=True):
    from code_agent.nemotron.dispatch import DispatchRecord
    from code_agent.nemotron.router import RoutingDecision
    from code_agent.nemotron.classifier import ClassificationResult
    from code_agent.active_agents.base import AgentResult

    return DispatchRecord(
        task=task,
        decision=RoutingDecision(
            classification=ClassificationResult(agent, 0.9, "test"),
            selected_agent=agent,
        ),
        result=AgentResult(agent_name=agent, output=output, success=success),
        total_duration_ms=100.0,
    )


class TestFeedbackLoop:
    def _make_loop(self, tmp_path, mean_score: float = 7.5, passed: bool = True):
        buf = ExperienceBuffer(str(tmp_path / "buf.db"))
        pol = RoutingPolicy(str(tmp_path / "pol.db"))
        trainer = OrchestraTrainer(buf, pol)

        verdict = CouncilVerdict(
            agent_name="claude_code",
            scores={d: mean_score for d in ["correctness", "completeness", "clarity", "efficiency", "safety"]},
            mean_score=mean_score,
            std_dev=0.0,
            judge_scores=[],
            quorum=1,
        )

        mock_council = MagicMock()
        mock_council.evaluate = AsyncMock(return_value=verdict)

        from code_agent.council.scorer import QualityGate
        gate = QualityGate(pass_threshold=6.0)

        return FeedbackLoop(
            council=mock_council,
            gate=gate,
            buffer=buf,
            policy=pol,
            trainer=trainer,
            auto_train_interval=5,
        )

    def test_evaluate_now_adds_to_buffer(self, tmp_path):
        loop = self._make_loop(tmp_path, mean_score=8.0)
        record = _make_dispatch_record()
        asyncio.run(loop.evaluate_now(record))
        recent = loop._buffer.recent(1)
        assert len(recent) == 1
        assert recent[0]["agent_name"] == "claude_code"

    def test_evaluate_now_updates_policy(self, tmp_path):
        loop = self._make_loop(tmp_path, mean_score=9.0)
        record = _make_dispatch_record()
        asyncio.run(loop.evaluate_now(record))
        ema = loop._policy.get_ema("claude_code", "coding")
        assert ema > 0.5  # high score → EMA above neutral

    def test_evaluate_now_skips_failed_dispatch(self, tmp_path):
        loop = self._make_loop(tmp_path)
        record = _make_dispatch_record(success=False, output="")
        result = asyncio.run(loop.evaluate_now(record))
        assert result is None
        assert loop._buffer.recent() == []

    def test_evaluate_now_skips_empty_output(self, tmp_path):
        loop = self._make_loop(tmp_path)
        record = _make_dispatch_record(output="")
        result = asyncio.run(loop.evaluate_now(record))
        assert result is None

    def test_auto_train_triggers_after_interval(self, tmp_path):
        loop = self._make_loop(tmp_path)
        loop._auto_train_interval = 2
        loop._trainer.train = MagicMock(return_value=TrainingReport(0, 0, False, 1.0))

        record = _make_dispatch_record()
        for _ in range(3):
            asyncio.run(loop.evaluate_now(record))

        assert loop._trainer.train.call_count >= 1

    def test_disabled_loop_skips_evaluation(self, tmp_path):
        loop = self._make_loop(tmp_path)
        loop._enabled = False
        loop.schedule(_make_dispatch_record())
        # No pending tasks added
        assert loop._pending == []

    def test_policy_boosts_returns_dict(self, tmp_path):
        loop = self._make_loop(tmp_path, mean_score=9.0)
        record = _make_dispatch_record()
        asyncio.run(loop.evaluate_now(record))
        boosts = loop.policy_boosts(["claude_code", "codex"], "coding")
        assert "claude_code" in boosts
        assert "codex" in boosts
        # claude_code got high reward → negative boost (higher priority)
        assert boosts["claude_code"] < 0

    def test_stats_structure(self, tmp_path):
        loop = self._make_loop(tmp_path)
        s = loop.stats()
        assert "buffer" in s
        assert "policy" in s
        assert "enabled" in s
        assert s["enabled"] is True

    def test_gate_result_is_qgr(self, tmp_path):
        loop = self._make_loop(tmp_path, mean_score=8.0, passed=True)
        record = _make_dispatch_record()
        result = asyncio.run(loop.evaluate_now(record))
        assert isinstance(result, QualityGateResult)
        assert result.passed is True
