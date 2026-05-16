"""Horizon Orchestra — Autonomous Heartbeat Daemon.

The heartbeat is a long-running background coroutine that periodically
executes configurable "checks" — small agent-powered tasks that monitor
inboxes, calendars, dashboards, and more. When a check's condition is
triggered, an alert is sent via the NotificationManager.

Mirrors OpenClaw's differentiator: an always-on ambient intelligence that
acts without being explicitly asked.

Usage::

    from orchestra.heartbeat import HeartbeatConfig, HeartbeatCheck, HeartbeatDaemon
    from orchestra.router import ModelRouter
    from orchestra.agent_loop import AgentLoop, create_default_tools, AgentConfig
    from orchestra.notifications import NotificationManager

    router = ModelRouter()
    tools = create_default_tools(router)
    agent_loop = AgentLoop(router, tools)
    notif = NotificationManager()

    config = HeartbeatConfig(interval_minutes=15, user_id="user_123")
    daemon = HeartbeatDaemon(config=config, agent_loop=agent_loop, notif=notif)
    daemon.start()
    # Runs forever in the background; call daemon.stop() to halt.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "HeartbeatConfig",
    "HeartbeatCheck",
    "HeartbeatResult",
    "HeartbeatDaemon",
    "DEFAULT_CHECKS",
]

log = logging.getLogger("orchestra.heartbeat")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HeartbeatCheck:
    """A single monitoring check run by the heartbeat daemon.

    Attributes:
        name: Unique check identifier.
        description: What this check does in plain English.
        tool_calls: List of tool names the agent should use (used as hints
            in the prompt; the agent is free to use others).
        condition: Plain-text description of when to raise an alert.
            E.g. "Alert if any email marked URGENT is found."
        priority: Check priority — ``"low"``, ``"medium"``, or ``"high"``.
        enabled: If False, the check is skipped.
        max_response_tokens: Max tokens for the agent's check response.
    """

    name: str
    description: str
    tool_calls: list[str] = field(default_factory=list)
    condition: str = ""
    priority: str = "medium"  # low | medium | high
    enabled: bool = True
    max_response_tokens: int = 1024


@dataclass
class HeartbeatResult:
    """Outcome of a single check execution.

    Attributes:
        check_name: Name of the check that ran.
        status: ``"ok"``, ``"alert"``, or ``"error"``.
        message: Human-readable summary of what was found.
        data: Arbitrary structured data from the check (e.g. email subjects).
        timestamp: Unix timestamp when the check completed.
        duration: Wall-clock time in seconds.
    """

    check_name: str
    status: str  # ok | alert | error
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    duration: float = 0.0


@dataclass
class HeartbeatConfig:
    """Configuration for the heartbeat daemon.

    Attributes:
        interval_minutes: How often to run all checks. Default: 15 minutes.
        checks: Initial list of :class:`HeartbeatCheck` objects.
        model: LLM model used by checks.
        user_id: User ID for notification delivery.
        enabled: Global on/off switch for the daemon.
        max_concurrent_checks: How many checks to run in parallel.
    """

    interval_minutes: int = 15
    checks: list[HeartbeatCheck] = field(default_factory=list)
    model: str = "kimi-k2.5"
    user_id: str = "default"
    enabled: bool = True
    max_concurrent_checks: int = 4


# ---------------------------------------------------------------------------
# Default checks
# ---------------------------------------------------------------------------

DEFAULT_CHECKS: list[HeartbeatCheck] = [
    HeartbeatCheck(
        name="inbox_scan",
        description=(
            "Scan the user's email inbox for urgent, important, or time-sensitive "
            "messages that require immediate attention."
        ),
        tool_calls=["memory_search"],
        condition=(
            "Alert if any email is flagged as URGENT, mentions a deadline within "
            "24 hours, or is from a VIP contact and has been unread for >2 hours."
        ),
        priority="high",
    ),
    HeartbeatCheck(
        name="calendar_review",
        description=(
            "Review the user's calendar for upcoming events in the next 2 hours "
            "and check if any preparation is needed."
        ),
        tool_calls=["memory_search"],
        condition=(
            "Alert if a meeting starts within 30 minutes and no preparation notes "
            "exist in memory."
        ),
        priority="high",
    ),
    HeartbeatCheck(
        name="monitoring_dashboard",
        description=(
            "Check system health metrics, CI/CD pipelines, error rates, or any "
            "monitored dashboards the user has configured."
        ),
        tool_calls=["web_search", "fetch_url"],
        condition=(
            "Alert if error rate exceeds threshold, a build is failing, or any "
            "critical metric is outside normal bounds."
        ),
        priority="medium",
    ),
    HeartbeatCheck(
        name="task_reminders",
        description=(
            "Review the user's tasks and to-dos. Identify any that are overdue "
            "or due within the next hour."
        ),
        tool_calls=["memory_search"],
        condition=(
            "Alert if any task is overdue by more than 1 hour or has a deadline "
            "within the next 30 minutes."
        ),
        priority="medium",
    ),
]


# ---------------------------------------------------------------------------
# HeartbeatDaemon
# ---------------------------------------------------------------------------

class HeartbeatDaemon:
    """Autonomous background agent that continuously monitors and alerts.

    The daemon runs an asyncio background task that sleeps between cycles.
    Each cycle executes all enabled checks concurrently (up to
    ``max_concurrent_checks``), evaluates their results, and sends
    notifications when alert conditions are met.

    Args:
        config: Daemon configuration.
        agent_loop: :class:`~orchestra.agent_loop.AgentLoop` instance used
            to execute checks. If None, a stub response is used.
        notif: :class:`~orchestra.notifications.NotificationManager` for
            alert delivery. If None, alerts are only logged.
    """

    def __init__(
        self,
        config: HeartbeatConfig | None = None,
        agent_loop: Any | None = None,  # AgentLoop
        notif: Any | None = None,  # NotificationManager
    ) -> None:
        self.config = config or HeartbeatConfig()
        self.agent_loop = agent_loop
        self.notif = notif
        self._checks: dict[str, HeartbeatCheck] = {}
        self._history: list[HeartbeatResult] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self._cycle_count = 0
        self._semaphore: asyncio.Semaphore | None = None

        # Register checks from config
        for check in self.config.checks:
            self._checks[check.name] = check

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background heartbeat loop.

        Creates an asyncio task that runs the check cycle repeatedly.
        Safe to call from a running event loop.

        Raises:
            RuntimeError: If the daemon is already running.
        """
        if self._running:
            log.warning("Heartbeat daemon is already running")
            return
        if not self.config.enabled:
            log.info("Heartbeat daemon is disabled (config.enabled=False)")
            return

        self._running = True
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent_checks)
        self._task = asyncio.ensure_future(self._loop())
        log.info(
            "Heartbeat daemon started (interval=%dm, checks=%d)",
            self.config.interval_minutes,
            len(self._checks),
        )

    def stop(self) -> None:
        """Stop the background heartbeat loop gracefully.

        The current cycle will complete before the daemon halts.
        """
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        log.info("Heartbeat daemon stopped after %d cycle(s)", self._cycle_count)

    # ------------------------------------------------------------------
    # Check management
    # ------------------------------------------------------------------

    def add_check(self, check: HeartbeatCheck) -> None:
        """Register a new check (or replace an existing one by name).

        Args:
            check: :class:`HeartbeatCheck` to add.
        """
        self._checks[check.name] = check
        log.debug("Added heartbeat check: %r", check.name)

    def remove_check(self, name: str) -> bool:
        """Remove a check by name.

        Args:
            name: Check name to remove.

        Returns:
            True if the check was found and removed, False otherwise.
        """
        if name in self._checks:
            del self._checks[name]
            log.debug("Removed heartbeat check: %r", name)
            return True
        return False

    def get_history(
        self,
        check_name: str | None = None,
        limit: int = 50,
    ) -> list[HeartbeatResult]:
        """Return recent check history, optionally filtered by check name.

        Args:
            check_name: If provided, only return results for this check.
            limit: Maximum number of results to return.

        Returns:
            List of :class:`HeartbeatResult` objects, newest first.
        """
        results = list(reversed(self._history))
        if check_name:
            results = [r for r in results if r.check_name == check_name]
        return results[:limit]

    # ------------------------------------------------------------------
    # Core cycle
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Main background loop. Runs until :meth:`stop` is called."""
        interval_seconds = self.config.interval_minutes * 60

        while self._running:
            try:
                cycle_start = time.monotonic()
                log.info("Heartbeat cycle #%d starting", self._cycle_count + 1)

                results = await self._run_cycle()
                self._cycle_count += 1
                cycle_duration = time.monotonic() - cycle_start

                alerts = [r for r in results if r.status == "alert"]
                log.info(
                    "Heartbeat cycle #%d complete in %.1fs: %d checks, %d alerts",
                    self._cycle_count, cycle_duration, len(results), len(alerts),
                )

                # Sleep until next cycle (subtract time already spent)
                sleep_seconds = max(0, interval_seconds - cycle_duration)
                await asyncio.sleep(sleep_seconds)

            except asyncio.CancelledError:
                log.debug("Heartbeat loop cancelled")
                break
            except Exception as exc:
                log.exception("Unexpected error in heartbeat loop: %s", exc)
                # Back off for 60 seconds on unexpected errors
                await asyncio.sleep(60)

    async def _run_cycle(self) -> list[HeartbeatResult]:
        """Execute all enabled checks in parallel.

        Returns:
            List of :class:`HeartbeatResult` for all checks that ran.
        """
        enabled_checks = [c for c in self._checks.values() if c.enabled]
        if not enabled_checks:
            return []

        tasks = [self._execute_check(check) for check in enabled_checks]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        final: list[HeartbeatResult] = []
        for check, result in zip(enabled_checks, results):
            if isinstance(result, Exception):
                error_result = HeartbeatResult(
                    check_name=check.name,
                    status="error",
                    message=f"Check raised an exception: {result}",
                )
                final.append(error_result)
                self._history.append(error_result)
            else:
                final.append(result)
                self._history.append(result)

                # Send notification if alerting
                if self._should_alert(result):
                    await self._send_alert(result)

        # Trim history to last 1000 results
        if len(self._history) > 1000:
            self._history = self._history[-1000:]

        return final

    async def _execute_check(self, check: HeartbeatCheck) -> HeartbeatResult:
        """Run a single check using the agent loop.

        Builds a task prompt from the check's description and condition,
        runs it through the agent loop (or a stub if unavailable), and
        parses the response to determine alert status.

        Args:
            check: The check to execute.

        Returns:
            :class:`HeartbeatResult`.
        """
        t0 = time.monotonic()
        log.debug("Executing check: %r", check.name)

        # Acquire concurrency semaphore
        async with self._semaphore or _NullContextManager():
            try:
                if self.agent_loop is None:
                    return HeartbeatResult(
                        check_name=check.name,
                        status="ok",
                        message="Agent loop not configured; check skipped.",
                        duration=time.monotonic() - t0,
                    )

                task_prompt = self._build_check_prompt(check)
                response_text = await self._run_agent_check(task_prompt, check)
                status, message, data = self._parse_check_response(
                    response_text, check
                )

                return HeartbeatResult(
                    check_name=check.name,
                    status=status,
                    message=message,
                    data=data,
                    duration=time.monotonic() - t0,
                )

            except Exception as exc:
                log.exception("Check %r failed: %s", check.name, exc)
                return HeartbeatResult(
                    check_name=check.name,
                    status="error",
                    message=str(exc),
                    duration=time.monotonic() - t0,
                )

    async def _run_agent_check(
        self, task_prompt: str, check: HeartbeatCheck
    ) -> str:
        """Dispatch the task to the agent loop and collect the final answer.

        Args:
            task_prompt: Formatted check prompt.
            check: The check configuration (used for tool hints).

        Returns:
            Agent's final answer text, or an empty string on failure.
        """
        from .agent_loop import FinalAnswerEvent, ErrorEvent

        final_text = ""
        try:
            async for event in self.agent_loop.run(task=task_prompt):
                if isinstance(event, FinalAnswerEvent):
                    final_text = event.content
                    break
                elif isinstance(event, ErrorEvent) and not event.recoverable:
                    log.warning("Agent error during check %r: %s", check.name, event.message)
                    break
        except Exception as exc:
            log.warning("Agent loop error for check %r: %s", check.name, exc)

        return final_text

    def _build_check_prompt(self, check: HeartbeatCheck) -> str:
        """Build the task prompt for a check.

        Args:
            check: Check configuration.

        Returns:
            Formatted task string.
        """
        tools_hint = ""
        if check.tool_calls:
            tools_hint = (
                f"\n\nSuggested tools to use: {', '.join(check.tool_calls)}"
            )

        return (
            f"HEARTBEAT CHECK: {check.name}\n\n"
            f"Task: {check.description}{tools_hint}\n\n"
            f"Alert condition: {check.condition or 'Alert if anything significant is found.'}\n\n"
            f"After performing your investigation, respond with a JSON object:\n"
            f'{{"status": "ok" or "alert", "message": "brief summary", '
            f'"data": {{...any relevant data...}}}}\n\n'
            f"Be concise. Do not ask for more information. Act autonomously."
        )

    def _parse_check_response(
        self,
        response_text: str,
        check: HeartbeatCheck,
    ) -> tuple[str, str, dict[str, Any]]:
        """Parse the agent's response into (status, message, data).

        Attempts to extract a JSON payload from the response. Falls back
        to keyword scanning for "alert" or "ok".

        Args:
            response_text: Raw agent response.
            check: Check configuration (used for fallback parsing).

        Returns:
            Tuple of ``(status, message, data)``.
        """
        import json
        import re

        # Try JSON extraction (greedy match for outermost object)
        m = re.search(r"\{[\s\S]*\}", response_text)
        if m:
            try:
                parsed = json.loads(m.group(0))
                status = parsed.get("status", "ok").lower()
                if status not in ("ok", "alert", "error"):
                    status = "ok"
                message = parsed.get("message", response_text[:200])
                data = parsed.get("data", {})
                return status, message, data
            except json.JSONDecodeError:
                pass

        # Keyword fallback
        lower = response_text.lower()
        if any(kw in lower for kw in ("alert", "urgent", "critical", "warning", "overdue")):
            return "alert", response_text[:500], {}
        return "ok", response_text[:500], {}

    def _should_alert(self, result: HeartbeatResult) -> bool:
        """Determine whether a result should trigger a notification.

        Args:
            result: Check result to evaluate.

        Returns:
            True if a notification should be sent.
        """
        if result.status == "alert":
            return True
        if result.status == "error":
            check = self._checks.get(result.check_name)
            return check is not None and check.priority == "high"
        return False

    async def _send_alert(self, result: HeartbeatResult) -> None:
        """Send a notification for an alerting check result.

        Args:
            result: The check result that triggered the alert.
        """
        check = self._checks.get(result.check_name)
        priority_emoji = {"high": "🚨", "medium": "⚠️", "low": "ℹ️"}.get(
            check.priority if check else "medium", "⚠️"
        )
        title = f"{priority_emoji} Heartbeat Alert: {result.check_name}"
        body = result.message or "Check triggered an alert."

        log.info("HEARTBEAT ALERT [%s]: %s", result.check_name, body[:200])

        if self.notif is not None:
            try:
                await self.notif.send(
                    user_id=self.config.user_id,
                    title=title,
                    body=body,
                    channel="in_app",
                    data=result.data,
                )
            except Exception as exc:
                log.warning("Failed to send heartbeat notification: %s", exc)


# ---------------------------------------------------------------------------
# Null context manager helper for optional semaphore
# ---------------------------------------------------------------------------

class _NullContextManager:
    """A no-op async context manager used when no semaphore is configured."""

    async def __aenter__(self) -> "_NullContextManager":
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass
