"""Horizon Orchestra — AgentNegotiator: Dynamic Task Bidding.

Agents dynamically bid on tasks.  The best-fit agent wins the assignment.

When a task arrives, the negotiator:

1. Broadcasts the task requirements to all eligible agents.
2. Collects bids (agents self-assess their fit).
3. Scores bids using a deterministic multi-factor formula.
4. Awards the task to the winning agent.
5. If no bids arrive (timeout), escalates to the coordinator.

Bid scoring formula::

    score = (capability_match × 0.40)
          + (confidence      × 0.25)
          + ((1 − load)      × 0.20)
          + (speed_score     × 0.15)

Supporting classes
------------------
- :class:`TaskBid` — A single agent's bid on a task.
- :class:`NegotiationResult` — Outcome of a negotiation round.

Example::

    negotiator = AgentNegotiator(team, bid_timeout_s=3.0)
    result = await negotiator.negotiate(task)
    if result.winner:
        print(f"Task awarded to {result.winner}")
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, List, Optional, Tuple

try:
    from .team import OrchestraTeam, TeamConfig, Specialist, TeamTask
except ImportError:  # pragma: no cover
    OrchestraTeam = object  # type: ignore[assignment,misc]
    TeamConfig = object  # type: ignore[assignment,misc]
    Specialist = object  # type: ignore[assignment,misc]
    TeamTask = object  # type: ignore[assignment,misc]

__all__ = [
    "AgentNegotiator",
    "TaskBid",
    "NegotiationResult",
]

log = logging.getLogger("orchestra.teams.negotiator")


# ==========================================================================
# Data models
# ==========================================================================

@dataclass
class TaskBid:
    """A single agent's bid on a task.

    Attributes
    ----------
    agent_id:
        Identifier of the bidding agent.
    task_id:
        Identifier of the task being bid on.
    confidence:
        0–1 self-assessed confidence that the agent can complete
        this task successfully.
    estimated_time_s:
        Estimated seconds to complete the task.
    cost_estimate:
        Abstract cost units (model tokens, API calls, etc.).
    capability_match:
        0–1 overlap between the task requirements and the agent's
        advertised capabilities.
    current_load:
        0–1 fraction indicating how busy the agent is right now.
    bid_timestamp:
        Unix timestamp when the bid was submitted.
    """

    agent_id: str
    task_id: str
    confidence: float
    estimated_time_s: float
    cost_estimate: float
    capability_match: float
    current_load: float
    bid_timestamp: float

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "confidence": self.confidence,
            "estimated_time_s": self.estimated_time_s,
            "cost_estimate": self.cost_estimate,
            "capability_match": self.capability_match,
            "current_load": self.current_load,
            "bid_timestamp": self.bid_timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskBid":
        """Deserialise from a dictionary."""
        return cls(**data)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<TaskBid agent={self.agent_id} task={self.task_id[:12]} "
            f"conf={self.confidence:.2f} match={self.capability_match:.2f} "
            f"load={self.current_load:.2f}>"
        )


@dataclass
class NegotiationResult:
    """Outcome of a negotiation round.

    Attributes
    ----------
    task_id:
        The task that was negotiated.
    winner:
        Agent ID that won the bid, or ``None`` if no bids were received.
    winning_bid:
        The winning :class:`TaskBid`, or ``None``.
    all_bids:
        All bids received during the negotiation.
    selection_reason:
        Human-readable explanation: ``"highest confidence"``,
        ``"fastest"``, ``"least loaded"``, ``"best overall score"``, etc.
    timeout:
        ``True`` if the negotiation timed out without receiving
        enough bids.
    """

    task_id: str
    winner: Optional[str] = None
    winning_bid: Optional[TaskBid] = None
    all_bids: List[TaskBid] = field(default_factory=list)
    selection_reason: str = ""
    timeout: bool = False

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "task_id": self.task_id,
            "winner": self.winner,
            "winning_bid": self.winning_bid.to_dict() if self.winning_bid else None,
            "all_bids": [b.to_dict() for b in self.all_bids],
            "selection_reason": self.selection_reason,
            "timeout": self.timeout,
            "bid_count": len(self.all_bids),
        }

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<NegotiationResult task={self.task_id[:12]} "
            f"winner={self.winner} bids={len(self.all_bids)} "
            f"timeout={self.timeout}>"
        )


# ==========================================================================
# SLA configuration
# ==========================================================================

@dataclass
class SLAConfig:
    """Service-level agreement configuration for task execution.

    Attributes
    ----------
    max_execution_time_s:
        Maximum allowed execution time per task in seconds.
    max_retries:
        Number of retry attempts before escalation.
    min_confidence:
        Minimum bid confidence to accept a task.
    escalation_timeout_s:
        Seconds to wait before escalating an SLA breach.
    """

    max_execution_time_s: float = 300.0
    max_retries: int = 2
    min_confidence: float = 0.3
    escalation_timeout_s: float = 30.0

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "max_execution_time_s": self.max_execution_time_s,
            "max_retries": self.max_retries,
            "min_confidence": self.min_confidence,
            "escalation_timeout_s": self.escalation_timeout_s,
        }


# ==========================================================================
# Internal: agent performance tracking
# ==========================================================================

@dataclass
class _AgentPerformanceRecord:
    """Internal record tracking an agent's negotiation history."""

    agent_id: str
    total_bids: int = 0
    total_wins: int = 0
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    total_sla_breaches: int = 0
    avg_bid_time_s: float = 0.0
    avg_execution_time_s: float = 0.0
    cumulative_confidence: float = 0.0
    last_bid_time: float = 0.0
    last_win_time: float = 0.0

    @property
    def win_rate(self) -> float:
        """Fraction of bids that were won."""
        return self.total_wins / self.total_bids if self.total_bids > 0 else 0.0

    @property
    def success_rate(self) -> float:
        """Fraction of won tasks that completed successfully."""
        total = self.total_tasks_completed + self.total_tasks_failed
        return self.total_tasks_completed / total if total > 0 else 1.0

    @property
    def avg_confidence(self) -> float:
        """Average confidence across all bids."""
        return self.cumulative_confidence / self.total_bids if self.total_bids > 0 else 0.0

    def to_dict(self) -> dict:
        """Serialise to a plain dictionary."""
        return {
            "agent_id": self.agent_id,
            "total_bids": self.total_bids,
            "total_wins": self.total_wins,
            "win_rate": round(self.win_rate, 4),
            "total_tasks_completed": self.total_tasks_completed,
            "total_tasks_failed": self.total_tasks_failed,
            "success_rate": round(self.success_rate, 4),
            "total_sla_breaches": self.total_sla_breaches,
            "avg_bid_time_s": round(self.avg_bid_time_s, 3),
            "avg_execution_time_s": round(self.avg_execution_time_s, 3),
            "avg_confidence": round(self.avg_confidence, 3),
        }


# ==========================================================================
# Scoring weights (module-level constants for determinism)
# ==========================================================================

_WEIGHT_CAPABILITY_MATCH = 0.40
_WEIGHT_CONFIDENCE = 0.25
_WEIGHT_AVAILABILITY = 0.20
_WEIGHT_SPEED = 0.15

# Maximum estimated time for speed normalisation (seconds)
_MAX_ESTIMATED_TIME_S = 600.0


# ==========================================================================
# AgentNegotiator
# ==========================================================================

class AgentNegotiator:
    """Agents bid on tasks.  The best-fit agent wins the task.

    When a task arrives the negotiator:

    1. Broadcasts the task requirements to all eligible agents.
    2. Collects bids (agents self-assess their fit).
    3. Scores bids using a deterministic multi-factor formula.
    4. Awards the task to the winning agent.
    5. If no bids arrive (timeout), escalates to the coordinator.

    The bid scoring formula is deterministic — identical inputs always
    produce the same score::

        score = (capability_match × 0.40)
              + (confidence      × 0.25)
              + ((1 − load)      × 0.20)
              + (speed_score     × 0.15)

    where ``speed_score = 1 − clamp(estimated_time / 600, 0, 1)``.

    Parameters
    ----------
    team:
        The :class:`OrchestraTeam` whose specialists participate.
    bid_timeout_s:
        Maximum seconds to wait for bids.
    min_bids:
        Minimum number of bids required before awarding.
    sla:
        Optional SLA configuration for enforcement.
    """

    def __init__(
        self,
        team: Any,
        bid_timeout_s: float = 5.0,
        min_bids: int = 1,
        sla: Optional[SLAConfig] = None,
    ) -> None:
        self._team = team
        self._bid_timeout_s = bid_timeout_s
        self._min_bids = max(1, min_bids)
        self._sla = sla or SLAConfig()

        # Performance tracking per agent
        self._performance: Dict[str, _AgentPerformanceRecord] = {}

        # Negotiation history
        self._history: Deque[NegotiationResult] = deque(maxlen=5_000)

        # Active SLA tracking: task_id → (agent_id, start_time, deadline)
        self._active_sla: Dict[str, Tuple[str, float, float]] = {}

        # Lock for concurrent negotiation safety
        self._lock = asyncio.Lock()

        log.debug(
            "AgentNegotiator initialised (timeout=%.1fs, min_bids=%d)",
            bid_timeout_s,
            min_bids,
        )

    # ==================================================================
    # Core negotiation
    # ==================================================================

    async def negotiate(self, task: Any) -> NegotiationResult:
        """Run a full negotiation round for *task*.

        Solicits bids from all eligible specialists, scores them,
        and awards the task to the winner.

        Parameters
        ----------
        task:
            A :class:`TeamTask` instance.

        Returns
        -------
        NegotiationResult
            The negotiation outcome.
        """
        task_id = getattr(task, "task_id", str(uuid.uuid4().hex[:12]))
        log.info("Negotiation started for task %s", task_id)

        # Step 1: Solicit bids
        bids = await self.solicit_bids(task)

        # Step 2: Handle no-bid / timeout case
        if len(bids) < self._min_bids:
            result = NegotiationResult(
                task_id=task_id,
                winner=None,
                winning_bid=None,
                all_bids=bids,
                selection_reason="insufficient bids received",
                timeout=True,
            )
            self._history.append(result)
            log.warning(
                "Negotiation for task %s timed out (%d bids, min=%d)",
                task_id,
                len(bids),
                self._min_bids,
            )
            return result

        # Step 3: Score all bids
        scored_bids: List[Tuple[TaskBid, float]] = []
        for bid in bids:
            score = await self.score_bid(bid, task)
            scored_bids.append((bid, score))

        # Sort by score descending (deterministic: ties broken by agent_id)
        scored_bids.sort(key=lambda x: (-x[1], x[0].agent_id))

        # Step 4: Select winner
        winner_bid, winner_score = scored_bids[0]

        # Determine selection reason
        selection_reason = self._determine_selection_reason(winner_bid, scored_bids)

        result = NegotiationResult(
            task_id=task_id,
            winner=winner_bid.agent_id,
            winning_bid=winner_bid,
            all_bids=bids,
            selection_reason=selection_reason,
            timeout=False,
        )

        # Step 5: Award task
        await self.award_task(result)
        self._history.append(result)

        log.info(
            "Task %s awarded to %s (score=%.3f, reason=%r)",
            task_id,
            winner_bid.agent_id,
            winner_score,
            selection_reason,
        )
        return result

    async def solicit_bids(self, task: Any) -> List[TaskBid]:
        """Broadcast the task and collect bids from eligible specialists.

        Parameters
        ----------
        task:
            A :class:`TeamTask` instance.

        Returns
        -------
        list[TaskBid]
            Collected bids (may be empty on timeout).
        """
        specialists = self._get_specialists()
        if not specialists:
            return []

        task_id = getattr(task, "task_id", "unknown")
        log.debug("Soliciting bids from %d specialists for task %s", len(specialists), task_id)

        # Collect bids concurrently with a timeout
        bid_tasks = [
            self._request_bid_with_timeout(spec, task)
            for spec in specialists
        ]

        try:
            bid_results = await asyncio.wait_for(
                asyncio.gather(*bid_tasks, return_exceptions=True),
                timeout=self._bid_timeout_s,
            )
        except asyncio.TimeoutError:
            log.warning("Bid collection timed out for task %s", task_id)
            bid_results = []

        # Filter valid bids
        bids: List[TaskBid] = []
        for result in bid_results:
            if isinstance(result, TaskBid):
                bids.append(result)
            elif isinstance(result, Exception):
                log.debug("Bid request failed: %s", result)

        log.debug("Collected %d bids for task %s", len(bids), task_id)
        return bids

    async def score_bid(self, bid: TaskBid, task: Any) -> float:
        """Score a bid using the deterministic multi-factor formula.

        The formula is::

            score = (capability_match × 0.40)
                  + (confidence      × 0.25)
                  + ((1 − load)      × 0.20)
                  + (speed_score     × 0.15)

        All inputs are clamped to [0, 1].  The output is in [0, 1].

        Parameters
        ----------
        bid:
            The bid to score.
        task:
            The task being bid on (used for context, not the score
            itself — the bid's ``capability_match`` already encodes
            the task–agent overlap).

        Returns
        -------
        float
            Score in [0.0, 1.0].
        """
        # Clamp inputs to [0, 1]
        capability_match = max(0.0, min(1.0, bid.capability_match))
        confidence = max(0.0, min(1.0, bid.confidence))
        load = max(0.0, min(1.0, bid.current_load))
        availability = 1.0 - load

        # Speed score: faster is better, normalised against max time
        estimated_time = max(0.0, bid.estimated_time_s)
        speed_ratio = min(estimated_time / _MAX_ESTIMATED_TIME_S, 1.0)
        speed_score = 1.0 - speed_ratio

        # Weighted sum
        score = (
            (_WEIGHT_CAPABILITY_MATCH * capability_match)
            + (_WEIGHT_CONFIDENCE * confidence)
            + (_WEIGHT_AVAILABILITY * availability)
            + (_WEIGHT_SPEED * speed_score)
        )

        return round(score, 6)

    async def award_task(self, result: NegotiationResult) -> None:
        """Award a task to the winning agent.

        Updates performance records and sets up SLA tracking.

        Parameters
        ----------
        result:
            The negotiation result containing the winner.
        """
        if result.winner is None:
            return

        # Update performance records for all bidders
        for bid in result.all_bids:
            rec = self._ensure_performance_record(bid.agent_id)
            rec.total_bids += 1
            rec.last_bid_time = bid.bid_timestamp
            # Running average of bid times (time to generate the bid)
            rec.cumulative_confidence += bid.confidence

        # Update winner's record
        winner_rec = self._ensure_performance_record(result.winner)
        winner_rec.total_wins += 1
        winner_rec.last_win_time = time.time()

        # Set up SLA tracking
        if result.winning_bid is not None:
            deadline = time.time() + self._sla.max_execution_time_s
            self._active_sla[result.task_id] = (
                result.winner,
                time.time(),
                deadline,
            )

        # Assign the task to the winning specialist
        specialists = self._get_specialists()
        for spec in specialists:
            if getattr(spec, "agent_id", None) == result.winner:
                spec.status = "active"
                spec.current_task = result.task_id
                log.debug("Specialist %s assigned task %s", spec.agent_id, result.task_id)
                break

    # ==================================================================
    # Agent self-assessment
    # ==================================================================

    async def request_bid(
        self,
        specialist: Any,
        task: Any,
    ) -> Optional[TaskBid]:
        """Request a bid from a single specialist.

        The specialist self-assesses its fitness for the task based
        on capability overlap, current load, and estimated time.

        Parameters
        ----------
        specialist:
            A :class:`Specialist` instance.
        task:
            A :class:`TeamTask` instance.

        Returns
        -------
        TaskBid or None
            The bid, or ``None`` if the specialist declines.
        """
        agent_id = getattr(specialist, "agent_id", "unknown")

        # Check availability
        status = getattr(specialist, "status", "idle")
        if status not in ("idle", "active"):
            log.debug("Specialist %s unavailable (status=%s)", agent_id, status)
            return None

        # Calculate capability match
        task_desc = getattr(task, "description", "")
        required_caps = getattr(task, "context", {}).get("required_capabilities", [])
        spec_caps = getattr(specialist, "capabilities", [])

        if required_caps:
            overlap = sum(1 for cap in required_caps if cap.lower() in [c.lower() for c in spec_caps])
            capability_match = overlap / len(required_caps) if required_caps else 0.0
        else:
            # Heuristic: check if any specialist capability appears in the
            # task description
            capability_match = self._heuristic_capability_match(spec_caps, task_desc)

        # Calculate current load
        current_task = getattr(specialist, "current_task", None)
        current_load = 0.8 if current_task else 0.0

        # Estimate confidence from capability match and historical performance
        perf = self._performance.get(agent_id)
        historical_success = perf.success_rate if perf else 1.0
        confidence = min(1.0, capability_match * 0.7 + historical_success * 0.3)

        # Minimum confidence gate: decline if too low
        if confidence < self._sla.min_confidence:
            log.debug(
                "Specialist %s declines task (confidence=%.2f < min=%.2f)",
                agent_id,
                confidence,
                self._sla.min_confidence,
            )
            return None

        # Estimate execution time (heuristic)
        base_time = 30.0  # base 30 seconds
        load_penalty = current_load * 60.0
        confidence_discount = (1.0 - confidence) * 120.0
        estimated_time = base_time + load_penalty + confidence_discount

        # Cost estimate (heuristic based on model tier)
        model = getattr(specialist, "model", "default")
        cost_estimate = self._estimate_cost(model, estimated_time)

        bid = TaskBid(
            agent_id=agent_id,
            task_id=getattr(task, "task_id", "unknown"),
            confidence=round(confidence, 4),
            estimated_time_s=round(estimated_time, 2),
            cost_estimate=round(cost_estimate, 2),
            capability_match=round(capability_match, 4),
            current_load=round(current_load, 4),
            bid_timestamp=time.time(),
        )

        log.debug(
            "Bid from %s: confidence=%.2f, match=%.2f, load=%.2f",
            agent_id,
            bid.confidence,
            bid.capability_match,
            bid.current_load,
        )
        return bid

    # ==================================================================
    # SLA enforcement
    # ==================================================================

    async def check_sla(self, task: Any, agent_id: str) -> bool:
        """Check whether *agent_id* is within SLA for *task*.

        Parameters
        ----------
        task:
            The task to check.
        agent_id:
            The agent executing the task.

        Returns
        -------
        bool
            ``True`` if within SLA, ``False`` if breached.
        """
        task_id = getattr(task, "task_id", "unknown")
        sla_entry = self._active_sla.get(task_id)
        if sla_entry is None:
            return True  # No SLA tracking for this task

        tracked_agent, start_time, deadline = sla_entry
        if tracked_agent != agent_id:
            return True  # Different agent, not our concern

        now = time.time()
        if now > deadline:
            log.warning(
                "SLA breach: agent %s exceeded deadline for task %s "
                "(elapsed=%.1fs, limit=%.1fs)",
                agent_id,
                task_id,
                now - start_time,
                self._sla.max_execution_time_s,
            )
            return False

        return True

    async def escalate_sla_breach(self, task: Any) -> None:
        """Escalate an SLA breach for a task.

        Marks the responsible agent's performance record and removes
        the SLA tracking entry.

        Parameters
        ----------
        task:
            The breached task.
        """
        task_id = getattr(task, "task_id", "unknown")
        sla_entry = self._active_sla.pop(task_id, None)
        if sla_entry is None:
            return

        agent_id, start_time, deadline = sla_entry
        elapsed = time.time() - start_time

        # Update performance
        rec = self._ensure_performance_record(agent_id)
        rec.total_sla_breaches += 1
        rec.total_tasks_failed += 1

        log.warning(
            "SLA escalation: agent %s, task %s (elapsed=%.1fs, limit=%.1fs)",
            agent_id,
            task_id,
            elapsed,
            self._sla.max_execution_time_s,
        )

    async def report_task_completion(
        self,
        task_id: str,
        agent_id: str,
        success: bool = True,
    ) -> None:
        """Report that a task has been completed (or failed).

        Updates performance records and clears SLA tracking.

        Parameters
        ----------
        task_id:
            The completed task.
        agent_id:
            The agent that executed it.
        success:
            ``True`` if the task completed successfully.
        """
        # Remove SLA tracking
        sla_entry = self._active_sla.pop(task_id, None)

        # Update performance
        rec = self._ensure_performance_record(agent_id)
        if success:
            rec.total_tasks_completed += 1
        else:
            rec.total_tasks_failed += 1

        # Update average execution time
        if sla_entry is not None:
            _, start_time, _ = sla_entry
            exec_time = time.time() - start_time
            total_completed = rec.total_tasks_completed + rec.total_tasks_failed
            if total_completed > 0:
                rec.avg_execution_time_s = (
                    (rec.avg_execution_time_s * (total_completed - 1) + exec_time)
                    / total_completed
                )

        # Release the specialist
        specialists = self._get_specialists()
        for spec in specialists:
            if getattr(spec, "agent_id", None) == agent_id:
                spec.status = "idle"
                spec.current_task = None
                break

    # ==================================================================
    # Load balancing
    # ==================================================================

    def get_agent_loads(self) -> Dict[str, float]:
        """Return current load for each specialist.

        Returns
        -------
        dict[str, float]
            Map of agent_id → load (0.0–1.0).
        """
        loads: Dict[str, float] = {}
        for spec in self._get_specialists():
            agent_id = getattr(spec, "agent_id", "unknown")
            current_task = getattr(spec, "current_task", None)
            loads[agent_id] = 0.8 if current_task else 0.0
        return loads

    def get_least_loaded(self) -> Any:
        """Return the specialist with the lowest current load.

        Returns
        -------
        Specialist or None
            The least-loaded specialist, or ``None`` if no specialists.
        """
        specialists = self._get_specialists()
        if not specialists:
            return None

        return min(
            specialists,
            key=lambda s: 0.8 if getattr(s, "current_task", None) else 0.0,
        )

    def get_most_capable(self, capabilities: List[str]) -> Any:
        """Return the specialist with the best capability match.

        Parameters
        ----------
        capabilities:
            Required capability tags.

        Returns
        -------
        Specialist or None
            Best-matching specialist, or ``None``.
        """
        specialists = self._get_specialists()
        if not specialists or not capabilities:
            return None

        def _overlap(spec: Any) -> int:
            spec_caps = [c.lower() for c in getattr(spec, "capabilities", [])]
            return sum(1 for cap in capabilities if cap.lower() in spec_caps)

        best = max(specialists, key=_overlap)
        if _overlap(best) == 0:
            return None
        return best

    # ==================================================================
    # Stats
    # ==================================================================

    def get_negotiation_stats(self) -> dict:
        """Return negotiation statistics.

        Returns
        -------
        dict
            Aggregate and per-agent negotiation metrics.
        """
        total_negotiations = len(self._history)
        successful = sum(1 for r in self._history if r.winner is not None)
        timed_out = sum(1 for r in self._history if r.timeout)

        avg_bids = 0.0
        if total_negotiations > 0:
            total_bids = sum(len(r.all_bids) for r in self._history)
            avg_bids = total_bids / total_negotiations

        return {
            "total_negotiations": total_negotiations,
            "successful_negotiations": successful,
            "timed_out_negotiations": timed_out,
            "success_rate": round(successful / total_negotiations, 4) if total_negotiations > 0 else 0.0,
            "average_bids_per_negotiation": round(avg_bids, 2),
            "active_sla_tasks": len(self._active_sla),
            "sla_config": self._sla.to_dict(),
            "agent_performance": {
                agent_id: rec.to_dict()
                for agent_id, rec in self._performance.items()
            },
        }

    # ==================================================================
    # Internal helpers
    # ==================================================================

    def _get_specialists(self) -> List[Any]:
        """Get the list of specialists from the team."""
        try:
            specialists_dict = getattr(self._team, "_specialists", {})
            return list(specialists_dict.values())
        except Exception:
            return []

    def _ensure_performance_record(self, agent_id: str) -> _AgentPerformanceRecord:
        """Get or create a performance record for an agent."""
        if agent_id not in self._performance:
            self._performance[agent_id] = _AgentPerformanceRecord(agent_id=agent_id)
        return self._performance[agent_id]

    async def _request_bid_with_timeout(
        self,
        specialist: Any,
        task: Any,
    ) -> Optional[TaskBid]:
        """Request a bid with a per-agent timeout.

        Wraps :meth:`request_bid` with an individual timeout guard.
        """
        try:
            return await asyncio.wait_for(
                self.request_bid(specialist, task),
                timeout=self._bid_timeout_s,
            )
        except asyncio.TimeoutError:
            agent_id = getattr(specialist, "agent_id", "unknown")
            log.debug("Bid request timed out for specialist %s", agent_id)
            return None
        except Exception as exc:
            agent_id = getattr(specialist, "agent_id", "unknown")
            log.debug("Bid request failed for specialist %s: %s", agent_id, exc)
            return None

    def _determine_selection_reason(
        self,
        winner: TaskBid,
        scored_bids: List[Tuple[TaskBid, float]],
    ) -> str:
        """Determine a human-readable reason for the winning bid.

        Analyses which factor contributed most to the winner's score.

        Parameters
        ----------
        winner:
            The winning bid.
        scored_bids:
            All (bid, score) pairs, sorted descending.

        Returns
        -------
        str
            Selection reason string.
        """
        if len(scored_bids) == 1:
            return "only bidder"

        # Find the dominant factor
        cap_contribution = _WEIGHT_CAPABILITY_MATCH * min(1.0, winner.capability_match)
        conf_contribution = _WEIGHT_CONFIDENCE * min(1.0, winner.confidence)
        avail_contribution = _WEIGHT_AVAILABILITY * (1.0 - min(1.0, winner.current_load))
        time_ratio = min(winner.estimated_time_s / _MAX_ESTIMATED_TIME_S, 1.0)
        speed_contribution = _WEIGHT_SPEED * (1.0 - time_ratio)

        contributions = {
            "best capability match": cap_contribution,
            "highest confidence": conf_contribution,
            "least loaded": avail_contribution,
            "fastest estimated time": speed_contribution,
        }

        dominant = max(contributions, key=contributions.get)  # type: ignore[arg-type]
        return f"best overall score ({dominant})"

    @staticmethod
    def _heuristic_capability_match(
        capabilities: List[str],
        task_description: str,
    ) -> float:
        """Heuristic match: fraction of capabilities that appear in the task.

        Parameters
        ----------
        capabilities:
            Agent's capability tags.
        task_description:
            The task's human-readable description.

        Returns
        -------
        float
            Match score in [0.0, 1.0].
        """
        if not capabilities or not task_description:
            return 0.0
        desc_lower = task_description.lower()
        matches = sum(1 for cap in capabilities if cap.lower() in desc_lower)
        return matches / len(capabilities)

    @staticmethod
    def _estimate_cost(model: str, estimated_time_s: float) -> float:
        """Heuristic cost estimate based on model and time.

        Parameters
        ----------
        model:
            Model identifier string.
        estimated_time_s:
            Estimated execution time.

        Returns
        -------
        float
            Abstract cost units.
        """
        # Tier-based cost multipliers
        tier_costs = {
            "gpt-4": 3.0,
            "gpt-4o": 2.0,
            "claude-3.5-sonnet": 2.5,
            "claude-3-opus": 4.0,
            "kimi-k2.5": 1.0,
            "gemini-2.0-flash": 0.5,
        }
        # Find the best matching cost tier
        multiplier = 1.0
        model_lower = model.lower()
        for key, cost in tier_costs.items():
            if key in model_lower:
                multiplier = cost
                break

        # Cost = multiplier × time factor
        time_factor = estimated_time_s / 60.0  # per-minute basis
        return round(multiplier * time_factor, 2)

    def __repr__(self) -> str:  # pragma: no cover
        specialists = self._get_specialists()
        return (
            f"<AgentNegotiator specialists={len(specialists)} "
            f"timeout={self._bid_timeout_s}s "
            f"negotiations={len(self._history)}>"
        )
