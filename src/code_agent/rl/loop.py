from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from code_agent.active_agents.base import AgentResult
from code_agent.council.council import ModelCouncil
from code_agent.council.scorer import QualityGate, QualityGateResult
from code_agent.nemotron.dispatch import DispatchRecord
from code_agent.rl.buffer import ExperienceBuffer
from code_agent.rl.policy import RoutingPolicy
from code_agent.rl.signal import TrainingSignal
from code_agent.rl.trainer import OrchestraTrainer

logger = logging.getLogger(__name__)

# How many signals before auto-triggering a policy re-train
_AUTO_TRAIN_INTERVAL = 10


class FeedbackLoop:
    """Connects the full learning pipeline:

        Dispatch result
          → Model Council evaluation (async, background)
          → Quality Gate → reward signal
          → Experience Buffer (persist)
          → Routing Policy EMA update
          → [Optional] OrchestraTrainer.train() every N signals

    Fire-and-forget: callers use `schedule(record)` which submits to a background
    task so the user response is never delayed by evaluation.
    """

    def __init__(
        self,
        council: ModelCouncil | None = None,
        gate: QualityGate | None = None,
        buffer: ExperienceBuffer | None = None,
        policy: RoutingPolicy | None = None,
        trainer: OrchestraTrainer | None = None,
        auto_train_interval: int = _AUTO_TRAIN_INTERVAL,
        enabled: bool = True,
    ):
        self._council = council or ModelCouncil()
        self._gate = gate or QualityGate()
        self._buffer = buffer or ExperienceBuffer()
        self._policy = policy or RoutingPolicy()
        self._trainer = trainer or OrchestraTrainer(self._buffer, self._policy)
        self._auto_train_interval = auto_train_interval
        self._enabled = enabled
        self._signals_since_train = 0
        self._pending: list[asyncio.Task] = []

    def schedule(self, record: DispatchRecord) -> None:
        """Submit background evaluation for a completed dispatch record."""
        if not self._enabled:
            return
        if not record.result.success or not record.result.output:
            return
        try:
            loop = asyncio.get_event_loop()
            task = loop.create_task(self._evaluate_and_learn(record))
            self._pending.append(task)
            task.add_done_callback(self._pending.remove)
        except RuntimeError:
            # No running event loop — skip background eval
            pass

    async def evaluate_now(self, record: DispatchRecord) -> QualityGateResult | None:
        """Synchronous (awaitable) version — useful for testing."""
        if not record.result.success or not record.result.output:
            return None
        return await self._evaluate_and_learn(record)

    async def _evaluate_and_learn(self, record: DispatchRecord) -> QualityGateResult | None:
        try:
            verdict = await self._council.evaluate(
                task=record.task,
                output=record.result.output,
                agent_name=record.result.agent_name,
            )
            gate_result = self._gate.evaluate(verdict, record.task)

            signal = TrainingSignal(
                task=record.task,
                agent_name=record.result.agent_name,
                task_category=gate_result.task_category,
                reward=gate_result.reward,
                council_mean=verdict.mean_score,
                dimension_scores=verdict.scores,
                passed_gate=gate_result.passed,
            )

            self._buffer.add(signal)
            new_ema = self._policy.update(
                agent_name=signal.agent_name,
                task_category=signal.task_category,
                reward=signal.reward,
            )

            self._signals_since_train += 1
            logger.debug(
                "Feedback: agent=%s cat=%s reward=%.3f ema→%.3f",
                signal.agent_name, signal.task_category, signal.reward, new_ema,
            )

            if self._signals_since_train >= self._auto_train_interval:
                self._signals_since_train = 0
                try:
                    self._trainer.train(run_lora=False)
                except Exception as e:
                    logger.warning("Auto-train failed: %s", e)

            return gate_result

        except Exception as e:
            logger.error("FeedbackLoop evaluation error: %s", e)
            return None

    def policy_boosts(self, agent_names: list[str], task_category: str) -> dict[str, float]:
        """Return priority boosts for all agents for the given task category."""
        return {
            name: self._policy.priority_boost(name, task_category)
            for name in agent_names
        }

    def stats(self) -> dict[str, Any]:
        return {
            "buffer": self._buffer.stats(),
            "policy": self._policy.summary(),
            "trainer": self._trainer.last_reports(5),
            "enabled": self._enabled,
            "pending_evaluations": len(self._pending),
        }
