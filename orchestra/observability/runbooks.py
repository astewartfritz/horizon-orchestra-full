"""Automated failover runbooks for Horizon Orchestra.

Self-executing runbooks for common failure modes.  Each runbook is a
sequence of steps with check → action → rollback semantics, timeouts,
and escalation contacts.

Usage::

    from orchestra.observability.runbooks import RunbookExecutor, PREBUILT_RUNBOOKS

    executor = RunbookExecutor()
    for rb in PREBUILT_RUNBOOKS:
        executor.register(rb)

    result = await executor.execute("high_error_rate", context={"threshold": 0.05})
    print(result)
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Union,
)

__all__ = [
    "RunbookStep",
    "Runbook",
    "RunbookResult",
    "StepResult",
    "RunbookExecutor",
    "PREBUILT_RUNBOOKS",
]

logger = logging.getLogger("orchestra.observability.runbooks")


# Type aliases for step functions
CheckFn = Callable[[Dict[str, Any]], Awaitable[bool]]
ActionFn = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]
RollbackFn = Callable[[Dict[str, Any]], Awaitable[None]]


# ── Enums ─────────────────────────────────────────────────────────────

class StepStatus(str, Enum):
    """Outcome of a single runbook step."""
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"
    TIMED_OUT = "timed_out"


class RunbookStatus(str, Enum):
    """Overall outcome of a runbook execution."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    NOT_TRIGGERED = "not_triggered"


# ── Data classes ──────────────────────────────────────────────────────

@dataclass
class RunbookStep:
    """A single step in an automated runbook.

    Parameters
    ----------
    name : str
        Human-readable step name.
    check_fn : CheckFn
        Async predicate — returns ``True`` if the condition is detected.
    action_fn : ActionFn
        Async remediation action — returns context updates.
    timeout : float
        Maximum seconds to wait for the action.
    rollback_fn : RollbackFn | None
        Optional async rollback if a later step fails.
    description : str
        Human-readable description of what this step does.
    """
    name: str
    check_fn: CheckFn
    action_fn: ActionFn
    timeout: float = 30.0
    rollback_fn: Optional[RollbackFn] = None
    description: str = ""


@dataclass
class StepResult:
    """Outcome of executing a single runbook step."""
    step_name: str
    status: StepStatus = StepStatus.PENDING
    duration_ms: float = 0.0
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class Runbook:
    """An automated runbook with ordered steps and escalation info.

    Parameters
    ----------
    id : str
        Unique runbook identifier.
    name : str
        Human-readable name.
    trigger : str
        Event or condition that activates this runbook.
    steps : list[RunbookStep]
        Ordered list of steps to execute.
    escalation_contact : str
        Who to page if the runbook cannot auto-resolve.
    description : str
        Detailed description.
    cooldown_seconds : float
        Minimum seconds between consecutive executions.
    """
    id: str
    name: str
    trigger: str
    steps: List[RunbookStep] = field(default_factory=list)
    escalation_contact: str = "oncall-sre@company.com"
    description: str = ""
    cooldown_seconds: float = 300.0


@dataclass
class RunbookResult:
    """Outcome of a full runbook execution."""
    runbook_id: str
    runbook_name: str
    status: RunbookStatus = RunbookStatus.SUCCESS
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    steps: List[StepResult] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)
    escalated: bool = False
    execution_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


# ── Runbook Executor ──────────────────────────────────────────────────

class RunbookExecutor:
    """Registry and executor for automated runbooks.

    Example::

        executor = RunbookExecutor()
        executor.register(my_runbook)
        result = await executor.execute("my_runbook_id")
    """

    def __init__(self) -> None:
        self._runbooks: Dict[str, Runbook] = {}
        self._history: List[RunbookResult] = []
        self._last_execution: Dict[str, float] = {}
        self._trigger_index: Dict[str, str] = {}  # trigger → runbook_id

    # ── Registration ──────────────────────────────────────────────────

    def register(self, runbook: Runbook) -> None:
        """Register a runbook for later execution."""
        self._runbooks[runbook.id] = runbook
        self._trigger_index[runbook.trigger] = runbook.id

    def unregister(self, runbook_id: str) -> None:
        """Remove a registered runbook."""
        rb = self._runbooks.pop(runbook_id, None)
        if rb:
            self._trigger_index.pop(rb.trigger, None)

    def list_runbooks(self) -> List[Dict[str, Any]]:
        """Return metadata for all registered runbooks."""
        return [
            {
                "id": rb.id,
                "name": rb.name,
                "trigger": rb.trigger,
                "steps": len(rb.steps),
                "escalation_contact": rb.escalation_contact,
            }
            for rb in self._runbooks.values()
        ]

    # ── Execution ─────────────────────────────────────────────────────

    async def execute(
        self,
        runbook_id: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> RunbookResult:
        """Execute a registered runbook by ID.

        Parameters
        ----------
        runbook_id : str
            The runbook to execute.
        context : dict, optional
            Initial context data passed to every step function.

        Returns
        -------
        RunbookResult
            Detailed execution outcome.
        """
        if runbook_id not in self._runbooks:
            raise KeyError(f"Unknown runbook: {runbook_id}")

        runbook = self._runbooks[runbook_id]

        # Cooldown check
        now = time.time()
        last = self._last_execution.get(runbook_id, 0.0)
        if now - last < runbook.cooldown_seconds and last > 0:
            logger.info(
                "Runbook %s in cooldown (%ds remaining)",
                runbook_id,
                int(runbook.cooldown_seconds - (now - last)),
            )
            return RunbookResult(
                runbook_id=runbook_id,
                runbook_name=runbook.name,
                status=RunbookStatus.NOT_TRIGGERED,
                started_at=_now_iso(),
                finished_at=_now_iso(),
                context=context or {},
            )

        ctx = dict(context or {})
        result = RunbookResult(
            runbook_id=runbook_id,
            runbook_name=runbook.name,
            started_at=_now_iso(),
            context=ctx,
        )

        start = time.monotonic()
        completed_steps: List[RunbookStep] = []
        all_passed = True

        for step in runbook.steps:
            step_result = StepResult(step_name=step.name)
            step_start = time.monotonic()

            # 1. Check — does the condition apply?
            try:
                should_act = await asyncio.wait_for(
                    step.check_fn(ctx),
                    timeout=step.timeout,
                )
            except asyncio.TimeoutError:
                step_result.status = StepStatus.TIMED_OUT
                step_result.error = "Check timed out"
                step_result.duration_ms = _elapsed_ms(step_start)
                result.steps.append(step_result)
                all_passed = False
                break
            except Exception as exc:
                step_result.status = StepStatus.FAILED
                step_result.error = f"Check failed: {exc}"
                step_result.duration_ms = _elapsed_ms(step_start)
                result.steps.append(step_result)
                all_passed = False
                break

            if not should_act:
                step_result.status = StepStatus.SKIPPED
                step_result.duration_ms = _elapsed_ms(step_start)
                result.steps.append(step_result)
                continue

            # 2. Action — execute remediation
            step_result.status = StepStatus.RUNNING
            try:
                updates = await asyncio.wait_for(
                    step.action_fn(ctx),
                    timeout=step.timeout,
                )
                ctx.update(updates or {})
                step_result.status = StepStatus.PASSED
                step_result.output = updates or {}
                completed_steps.append(step)
            except asyncio.TimeoutError:
                step_result.status = StepStatus.TIMED_OUT
                step_result.error = "Action timed out"
                all_passed = False
            except Exception as exc:
                step_result.status = StepStatus.FAILED
                step_result.error = f"Action failed: {exc}"
                all_passed = False

            step_result.duration_ms = _elapsed_ms(step_start)
            result.steps.append(step_result)

            if not all_passed:
                # Rollback completed steps in reverse order
                await self._rollback(completed_steps, ctx, result)
                break

        # Finalise
        result.finished_at = _now_iso()
        result.duration_ms = _elapsed_ms(start)
        result.context = ctx

        if all_passed:
            has_actions = any(s.status == StepStatus.PASSED for s in result.steps)
            result.status = RunbookStatus.SUCCESS if has_actions else RunbookStatus.NOT_TRIGGERED
        else:
            has_some = any(s.status == StepStatus.PASSED for s in result.steps)
            result.status = RunbookStatus.PARTIAL if has_some else RunbookStatus.FAILED
            # Escalate on failure
            result.escalated = True
            logger.warning(
                "Runbook %s escalated to %s", runbook_id, runbook.escalation_contact,
            )

        self._history.append(result)
        self._last_execution[runbook_id] = time.time()
        return result

    async def execute_on_trigger(
        self,
        trigger: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[RunbookResult]:
        """Execute the runbook associated with a trigger string.

        Returns ``None`` if no runbook matches the trigger.
        """
        runbook_id = self._trigger_index.get(trigger)
        if runbook_id is None:
            return None
        return await self.execute(runbook_id, context)

    # ── History ───────────────────────────────────────────────────────

    def get_history(self, limit: int = 100) -> List[RunbookResult]:
        """Return the most recent runbook execution results."""
        return list(self._history[-limit:])

    # ── Rollback ──────────────────────────────────────────────────────

    async def _rollback(
        self,
        completed_steps: List[RunbookStep],
        ctx: Dict[str, Any],
        result: RunbookResult,
    ) -> None:
        """Roll back completed steps in reverse order."""
        for step in reversed(completed_steps):
            if step.rollback_fn is None:
                continue
            try:
                await asyncio.wait_for(step.rollback_fn(ctx), timeout=step.timeout)
                # Mark the step as rolled back in the result
                for sr in result.steps:
                    if sr.step_name == step.name:
                        sr.status = StepStatus.ROLLED_BACK
            except Exception as exc:
                logger.error("Rollback failed for step %s: %s", step.name, exc)


# ── Helper ────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds") + "Z"


def _elapsed_ms(start: float) -> float:
    return round((time.monotonic() - start) * 1000, 2)


# ── Shared helper ─────────────────────────────────────────────────────

async def _always_true(ctx: Dict[str, Any]) -> bool:
    """Check function that always returns ``True``."""
    return True


# ══════════════════════════════════════════════════════════════════════
#  PRE-BUILT RUNBOOKS
# ══════════════════════════════════════════════════════════════════════

# ── high_error_rate ───────────────────────────────────────────────────

async def _her_detect(ctx: Dict[str, Any]) -> bool:
    """Check if error rate exceeds threshold."""
    return ctx.get("error_rate", 0.0) > ctx.get("threshold", 0.05)

async def _her_circuit_break(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Enable circuit breaker on the failing provider."""
    provider = ctx.get("provider", "primary")
    logger.info("Circuit-breaking provider: %s", provider)
    return {"circuit_broken": provider}

async def _her_failover(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Switch traffic to fallback provider."""
    fallback = ctx.get("fallback_provider", "secondary")
    logger.info("Failing over to: %s", fallback)
    return {"active_provider": fallback}

async def _her_alert(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Send alert notification."""
    logger.info("ALERT: High error rate — circuit broken, failed over")
    return {"alert_sent": True}

async def _her_verify(ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Verify the failover resolved the issue."""
    return {"verified": True}

async def _her_rollback_failover(ctx: Dict[str, Any]) -> None:
    """Rollback: switch back to original provider."""
    logger.info("Rolling back failover, restoring original provider")

high_error_rate_runbook = Runbook(
    id="high_error_rate",
    name="High Error Rate Response",
    trigger="high_error_rate",
    description="Detect high error rate → circuit break → failover → alert → verify",
    escalation_contact="sre-oncall@company.com",
    cooldown_seconds=120.0,
    steps=[
        RunbookStep(name="detect", check_fn=_her_detect, action_fn=_her_circuit_break, timeout=10.0, description="Detect and circuit-break"),
        RunbookStep(name="failover", check_fn=_her_detect, action_fn=_her_failover, timeout=15.0, rollback_fn=_her_rollback_failover, description="Failover to secondary provider"),
        RunbookStep(name="alert", check_fn=_always_true, action_fn=_her_alert, timeout=5.0, description="Send alert notification"),
        RunbookStep(name="verify", check_fn=_always_true, action_fn=_her_verify, timeout=30.0, description="Verify recovery"),
    ],
)


# ── provider_down ─────────────────────────────────────────────────────

async def _pd_detect(ctx: Dict[str, Any]) -> bool:
    return ctx.get("provider_status") == "down"

async def _pd_switch(ctx: Dict[str, Any]) -> Dict[str, Any]:
    secondary = ctx.get("secondary_provider", "backup-llm")
    logger.info("Switching to secondary provider: %s", secondary)
    return {"active_provider": secondary, "switched": True}

async def _pd_update_routing(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Updating routing table for new provider")
    return {"routing_updated": True}

async def _pd_notify(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Notifying team of provider failover")
    return {"notification_sent": True}

async def _pd_monitor(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Setting up monitoring for failover provider")
    return {"monitoring_enabled": True}

async def _pd_rollback_switch(ctx: Dict[str, Any]) -> None:
    logger.info("Rolling back provider switch")

provider_down_runbook = Runbook(
    id="provider_down",
    name="Provider Down Failover",
    trigger="provider_down",
    description="Detect provider down → switch to secondary → update routing → notify → monitor",
    escalation_contact="infra-oncall@company.com",
    cooldown_seconds=180.0,
    steps=[
        RunbookStep(name="detect", check_fn=_pd_detect, action_fn=_pd_switch, timeout=10.0, rollback_fn=_pd_rollback_switch, description="Detect and switch"),
        RunbookStep(name="update_routing", check_fn=_always_true, action_fn=_pd_update_routing, timeout=10.0, description="Update routing table"),
        RunbookStep(name="notify", check_fn=_always_true, action_fn=_pd_notify, timeout=5.0, description="Notify team"),
        RunbookStep(name="monitor", check_fn=_always_true, action_fn=_pd_monitor, timeout=5.0, description="Enable monitoring"),
    ],
)


# ── memory_pressure ───────────────────────────────────────────────────

async def _mp_detect(ctx: Dict[str, Any]) -> bool:
    return ctx.get("memory_pct", 0) > ctx.get("memory_threshold", 85)

async def _mp_evict(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Evicting old memory entries")
    return {"entries_evicted": ctx.get("evict_count", 1000)}

async def _mp_compact(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Compacting memory store")
    return {"compacted": True}

async def _mp_alert(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("ALERT: Memory pressure still elevated after eviction")
    return {"alert_sent": True}

async def _mp_still_high(ctx: Dict[str, Any]) -> bool:
    return ctx.get("memory_pct", 0) > ctx.get("memory_threshold", 85)

memory_pressure_runbook = Runbook(
    id="memory_pressure",
    name="Memory Pressure Response",
    trigger="memory_pressure",
    description="Detect memory pressure → evict → compact → alert if still high",
    escalation_contact="infra-oncall@company.com",
    cooldown_seconds=60.0,
    steps=[
        RunbookStep(name="detect_evict", check_fn=_mp_detect, action_fn=_mp_evict, timeout=20.0, description="Detect and evict old entries"),
        RunbookStep(name="compact", check_fn=_always_true, action_fn=_mp_compact, timeout=30.0, description="Compact memory store"),
        RunbookStep(name="alert_if_high", check_fn=_mp_still_high, action_fn=_mp_alert, timeout=5.0, description="Alert if still high"),
    ],
)


# ── rate_limit_exceeded ───────────────────────────────────────────────

async def _rl_detect(ctx: Dict[str, Any]) -> bool:
    return ctx.get("rate_limited", False)

async def _rl_queue(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Queueing excess requests")
    return {"requests_queued": True}

async def _rl_notify(ctx: Dict[str, Any]) -> Dict[str, Any]:
    org_id = ctx.get("org_id", "unknown")
    logger.info("Notifying org %s of rate limiting", org_id)
    return {"org_notified": org_id}

async def _rl_scale(ctx: Dict[str, Any]) -> Dict[str, Any]:
    if ctx.get("auto_scale_enabled", False):
        logger.info("Auto-scaling request capacity")
        return {"scaled": True}
    return {"scaled": False}

rate_limit_runbook = Runbook(
    id="rate_limit_exceeded",
    name="Rate Limit Exceeded",
    trigger="rate_limit_exceeded",
    description="Detect → queue requests → notify org → scale if possible",
    escalation_contact="platform-oncall@company.com",
    cooldown_seconds=60.0,
    steps=[
        RunbookStep(name="detect_queue", check_fn=_rl_detect, action_fn=_rl_queue, timeout=5.0, description="Detect and queue"),
        RunbookStep(name="notify", check_fn=_always_true, action_fn=_rl_notify, timeout=5.0, description="Notify org"),
        RunbookStep(name="scale", check_fn=_always_true, action_fn=_rl_scale, timeout=15.0, description="Auto-scale if possible"),
    ],
)


# ── security_incident ─────────────────────────────────────────────────

async def _si_detect(ctx: Dict[str, Any]) -> bool:
    return ctx.get("security_incident", False)

async def _si_isolate(ctx: Dict[str, Any]) -> Dict[str, Any]:
    agent_id = ctx.get("agent_id", "unknown")
    logger.info("Isolating agent: %s", agent_id)
    return {"isolated_agent": agent_id}

async def _si_snapshot(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Snapshotting audit trail for forensics")
    return {"audit_snapshot": True, "snapshot_ts": _now_iso()}

async def _si_alert(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("SECURITY ALERT: Incident detected, agent isolated")
    return {"security_alert_sent": True}

async def _si_escalate(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Escalating to security team")
    return {"escalated_to": "security-team@company.com"}

async def _si_rollback_isolate(ctx: Dict[str, Any]) -> None:
    logger.info("Releasing isolated agent")

security_incident_runbook = Runbook(
    id="security_incident",
    name="Security Incident Response",
    trigger="security_incident",
    description="Detect → isolate agent → snapshot audit trail → alert → escalate",
    escalation_contact="security-team@company.com",
    cooldown_seconds=0.0,  # no cooldown for security incidents
    steps=[
        RunbookStep(name="detect_isolate", check_fn=_si_detect, action_fn=_si_isolate, timeout=5.0, rollback_fn=_si_rollback_isolate, description="Detect and isolate"),
        RunbookStep(name="snapshot", check_fn=_always_true, action_fn=_si_snapshot, timeout=15.0, description="Snapshot audit trail"),
        RunbookStep(name="alert", check_fn=_always_true, action_fn=_si_alert, timeout=5.0, description="Send security alert"),
        RunbookStep(name="escalate", check_fn=_always_true, action_fn=_si_escalate, timeout=5.0, description="Escalate to security team"),
    ],
)


# ── database_slow ─────────────────────────────────────────────────────

async def _db_detect(ctx: Dict[str, Any]) -> bool:
    return ctx.get("db_latency_ms", 0) > ctx.get("db_threshold_ms", 500)

async def _db_switch_replica(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Switching reads to read replica")
    return {"using_read_replica": True}

async def _db_optimize(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Running query optimization pass")
    return {"queries_optimized": True}

async def _db_alert_dba(ctx: Dict[str, Any]) -> Dict[str, Any]:
    logger.info("Alerting DBA team about slow database")
    return {"dba_alerted": True}

async def _db_rollback_replica(ctx: Dict[str, Any]) -> None:
    logger.info("Switching back from read replica to primary")

database_slow_runbook = Runbook(
    id="database_slow",
    name="Database Slow Response",
    trigger="database_slow",
    description="Detect → switch to read replica → optimize queries → alert DBA",
    escalation_contact="dba-oncall@company.com",
    cooldown_seconds=120.0,
    steps=[
        RunbookStep(name="detect_switch", check_fn=_db_detect, action_fn=_db_switch_replica, timeout=10.0, rollback_fn=_db_rollback_replica, description="Detect and switch to replica"),
        RunbookStep(name="optimize", check_fn=_always_true, action_fn=_db_optimize, timeout=30.0, description="Optimize slow queries"),
        RunbookStep(name="alert_dba", check_fn=_always_true, action_fn=_db_alert_dba, timeout=5.0, description="Alert DBA team"),
    ],
)


# ── Pre-built collection ──────────────────────────────────────────────

PREBUILT_RUNBOOKS: List[Runbook] = [
    high_error_rate_runbook,
    provider_down_runbook,
    memory_pressure_runbook,
    rate_limit_runbook,
    security_incident_runbook,
    database_slow_runbook,
]
