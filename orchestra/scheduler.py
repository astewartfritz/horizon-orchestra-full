"""Horizon Orchestra — Cron Scheduler.

Recurring tasks, background jobs, time-triggered workflows.
Horizon Prince scheduled task system: cron expressions,
one-shot delayed execution, and persistent job history.

Uses asyncio for the scheduler loop — swap to APScheduler or Celery
Beat for production multi-worker deployments.

Usage::

    from orchestra.scheduler import Scheduler, CronJob

    scheduler = Scheduler()
    scheduler.add("daily_report", "0 9 * * *", "Generate daily metrics report")
    scheduler.add("hourly_check", "0 * * * *", "Check inbox for urgent emails")
    await scheduler.start()
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Awaitable

__all__ = ["Scheduler", "CronJob", "JobRun", "parse_cron"]

log = logging.getLogger("orchestra.scheduler")


# ---------------------------------------------------------------------------
# Cron parsing (minute, hour, day, month, weekday)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CronSchedule:
    minute: set[int]
    hour: set[int]
    day: set[int]
    month: set[int]
    weekday: set[int]   # 0=Monday ... 6=Sunday

    def matches(self, dt: datetime) -> bool:
        return (
            dt.minute in self.minute
            and dt.hour in self.hour
            and dt.day in self.day
            and dt.month in self.month
            and dt.weekday() in self.weekday
        )

    def next_run(self, after: datetime) -> datetime:
        """Find the next datetime matching this schedule after *after*."""
        candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(525_960):  # max ~1 year of minutes
            if self.matches(candidate):
                return candidate
            candidate += timedelta(minutes=1)
        return candidate


def _parse_field(field_str: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field (e.g. '*/5', '1,15', '1-5')."""
    values: set[int] = set()
    for part in field_str.split(","):
        part = part.strip()
        if part == "*":
            values.update(range(min_val, max_val + 1))
        elif "/" in part:
            base, step = part.split("/", 1)
            start = min_val if base == "*" else int(base)
            values.update(range(start, max_val + 1, int(step)))
        elif "-" in part:
            lo, hi = part.split("-", 1)
            values.update(range(int(lo), int(hi) + 1))
        else:
            values.add(int(part))
    return values


def parse_cron(expr: str) -> CronSchedule:
    """Parse a 5-field cron expression.

    Format: ``minute hour day month weekday``

    Examples:
    - ``0 9 * * *``       → 9:00 AM daily
    - ``*/15 * * * *``    → every 15 minutes
    - ``0 9,17 * * 1-5``  → 9 AM and 5 PM, weekdays only
    """
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"Cron expression must have 5 fields, got {len(parts)}: {expr!r}")

    return CronSchedule(
        minute=_parse_field(parts[0], 0, 59),
        hour=_parse_field(parts[1], 0, 23),
        day=_parse_field(parts[2], 1, 31),
        month=_parse_field(parts[3], 1, 12),
        weekday=_parse_field(parts[4], 0, 6),
    )


# ---------------------------------------------------------------------------
# Job data structures
# ---------------------------------------------------------------------------

@dataclass
class CronJob:
    """A scheduled recurring job."""
    id: str
    name: str
    cron: str
    task: str                           # natural language task for the agent
    schedule: CronSchedule = field(repr=False, default=None)
    enabled: bool = True
    created_at: float = field(default_factory=time.time)
    last_run: float = 0.0
    run_count: int = 0
    user_id: str = "default"
    architecture: str = "A"             # which architecture to use
    max_retries: int = 1

    def __post_init__(self):
        if self.schedule is None:
            self.schedule = parse_cron(self.cron)


@dataclass
class JobRun:
    """Record of a single job execution."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    job_id: str = ""
    job_name: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
    duration: float = 0.0
    status: str = "pending"             # pending, running, success, failed
    result: str = ""
    error: str = ""


@dataclass
class DelayedJob:
    """A one-shot delayed task."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task: str = ""
    run_at: float = 0.0
    user_id: str = "default"
    architecture: str = "A"
    status: str = "pending"


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

class Scheduler:
    """Asyncio-based cron scheduler.

    Runs a background loop that checks every 30 seconds for jobs whose
    cron schedule matches the current time. When a match is found, the
    job's task is dispatched to the orchestrator.
    """

    def __init__(self, orchestrator_factory: Callable[..., Any] | None = None) -> None:
        self._jobs: dict[str, CronJob] = {}
        self._delayed: dict[str, DelayedJob] = {}
        self._history: list[JobRun] = []
        self._running = False
        self._task: asyncio.Task | None = None
        self._orchestrator_factory = orchestrator_factory
        self._check_interval = 30  # seconds

    # -- job management -----------------------------------------------------

    def add(
        self,
        name: str,
        cron: str,
        task: str,
        user_id: str = "default",
        architecture: str = "A",
    ) -> CronJob:
        """Add a recurring cron job."""
        job = CronJob(
            id=str(uuid.uuid4())[:8],
            name=name,
            cron=cron,
            task=task,
            user_id=user_id,
            architecture=architecture,
        )
        self._jobs[job.id] = job
        log.info("Added cron job: %s [%s] '%s'", name, cron, task[:60])
        return job

    def add_delayed(
        self,
        task: str,
        delay_minutes: int,
        user_id: str = "default",
        architecture: str = "A",
    ) -> DelayedJob:
        """Add a one-shot delayed task."""
        job = DelayedJob(
            task=task,
            run_at=time.time() + delay_minutes * 60,
            user_id=user_id,
            architecture=architecture,
        )
        self._delayed[job.id] = job
        log.info("Added delayed job: %s (in %dm)", job.id, delay_minutes)
        return job

    def remove(self, job_id: str) -> bool:
        if job_id in self._jobs:
            del self._jobs[job_id]
            return True
        if job_id in self._delayed:
            del self._delayed[job_id]
            return True
        return False

    def enable(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job:
            job.enabled = True
            return True
        return False

    def disable(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job:
            job.enabled = False
            return True
        return False

    def list_jobs(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        out = []
        for j in self._jobs.values():
            next_run = j.schedule.next_run(now)
            out.append({
                "id": j.id, "name": j.name, "cron": j.cron,
                "task": j.task[:80], "enabled": j.enabled,
                "run_count": j.run_count,
                "next_run": next_run.isoformat(),
                "architecture": j.architecture,
            })
        return out

    def list_delayed(self) -> list[dict[str, Any]]:
        return [
            {"id": d.id, "task": d.task[:80], "run_at": d.run_at, "status": d.status}
            for d in self._delayed.values()
        ]

    def get_history(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "id": r.id, "job_id": r.job_id, "job_name": r.job_name,
                "status": r.status, "duration": r.duration,
                "started_at": r.started_at, "result": r.result[:200],
                "error": r.error[:200] if r.error else "",
            }
            for r in sorted(self._history, key=lambda x: x.started_at, reverse=True)[:limit]
        ]

    # -- scheduler loop -----------------------------------------------------

    async def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        log.info("Scheduler started (%d jobs)", len(self._jobs))

    async def stop(self) -> None:
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        log.info("Scheduler stopped")

    async def _loop(self) -> None:
        """Main scheduler loop."""
        last_checked_minute = -1

        while self._running:
            try:
                now = datetime.now(timezone.utc)

                # -- cron jobs (check once per minute) ----------------------
                current_minute = now.minute + now.hour * 60
                if current_minute != last_checked_minute:
                    last_checked_minute = current_minute
                    for job in list(self._jobs.values()):
                        if job.enabled and job.schedule.matches(now):
                            asyncio.create_task(self._execute_job(job))

                # -- delayed jobs -------------------------------------------
                now_ts = time.time()
                for dj in list(self._delayed.values()):
                    if dj.status == "pending" and now_ts >= dj.run_at:
                        dj.status = "running"
                        asyncio.create_task(self._execute_delayed(dj))

                await asyncio.sleep(self._check_interval)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("Scheduler loop error: %s", exc)
                await asyncio.sleep(self._check_interval)

    async def _execute_job(self, job: CronJob) -> None:
        """Execute a cron job."""
        run = JobRun(job_id=job.id, job_name=job.name, started_at=time.time(), status="running")

        try:
            if self._orchestrator_factory:
                orch = self._orchestrator_factory(
                    user_id=job.user_id,
                    architecture=job.architecture,
                )
                result = await orch.run(job.task)
                run.result = result[:5000]
                run.status = "success"
            else:
                run.result = "[No orchestrator configured]"
                run.status = "success"
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            log.error("Job %s failed: %s", job.name, exc)

        run.completed_at = time.time()
        run.duration = run.completed_at - run.started_at
        job.last_run = run.completed_at
        job.run_count += 1
        self._history.append(run)

        log.info("Job %s completed: %s (%.1fs)", job.name, run.status, run.duration)

    async def _execute_delayed(self, job: DelayedJob) -> None:
        """Execute a delayed one-shot job."""
        try:
            if self._orchestrator_factory:
                orch = self._orchestrator_factory(
                    user_id=job.user_id,
                    architecture=job.architecture,
                )
                await orch.run(job.task)
            job.status = "complete"
        except Exception as exc:
            job.status = "failed"
            log.error("Delayed job %s failed: %s", job.id, exc)
        finally:
            # Remove from active delayed jobs
            self._delayed.pop(job.id, None)
