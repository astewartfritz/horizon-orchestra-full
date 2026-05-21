from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from orchestra.code_agent.active_agents.base import AgentResult
from orchestra.code_agent.nemotron.router import NemotronRouter, RoutingDecision

if TYPE_CHECKING:
    from orchestra.code_agent.rl.loop import FeedbackLoop

logger = logging.getLogger(__name__)


@dataclass
class DispatchRecord:
    task: str
    decision: RoutingDecision
    result: AgentResult
    total_duration_ms: float
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_preview": self.task[:120],
            "agent_used": self.result.agent_name,
            "success": self.result.success,
            "routing": self.decision.to_dict(),
            "total_duration_ms": self.total_duration_ms,
            "timestamp": self.timestamp,
        }


class NemotronDispatch:
    """High-level dispatcher: receives a task, routes via Nemotron, executes, records outcome.

    If a FeedbackLoop is attached, council evaluation runs asynchronously in the
    background after each successful dispatch — the user response is never delayed.
    Over time the routing policy learns which agents produce the best outputs.
    """

    def __init__(
        self,
        router: NemotronRouter,
        history_limit: int = 100,
        feedback_loop: "FeedbackLoop | None" = None,
    ):
        self._router = router
        self._history: list[DispatchRecord] = []
        self._history_limit = history_limit
        self._feedback_loop = feedback_loop

    def attach_feedback_loop(self, loop: "FeedbackLoop") -> None:
        """Attach (or replace) the feedback loop post-construction."""
        self._feedback_loop = loop

    async def dispatch(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        skip_health_check: bool = False,
    ) -> DispatchRecord:
        start = time.time()
        decision, result = await self._router.route_and_execute(
            task, context=context, skip_health_check=skip_health_check
        )
        record = DispatchRecord(
            task=task,
            decision=decision,
            result=result,
            total_duration_ms=(time.time() - start) * 1000,
        )
        self._record(record)

        # Fire-and-forget council evaluation → learning signal
        if self._feedback_loop is not None:
            self._feedback_loop.schedule(record)

        return record

    def _record(self, record: DispatchRecord) -> None:
        self._history.append(record)
        if len(self._history) > self._history_limit:
            self._history = self._history[-self._history_limit :]

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        return [r.to_dict() for r in self._history[-limit:]]

    def stats(self) -> dict[str, Any]:
        if not self._history:
            return {"total": 0, "success_rate": 0.0, "agents_used": {}}
        total = len(self._history)
        successes = sum(1 for r in self._history if r.result.success)
        agents: dict[str, int] = {}
        for r in self._history:
            agents[r.result.agent_name] = agents.get(r.result.agent_name, 0) + 1
        avg_ms = sum(r.total_duration_ms for r in self._history) / total
        return {
            "total": total,
            "success_rate": successes / total,
            "agents_used": agents,
            "avg_duration_ms": round(avg_ms, 1),
        }
