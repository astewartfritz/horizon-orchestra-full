"""Horizon Orchestra — Persistent Task System.

Long-running, pauseable, schedulable agent tasks with filesystem-based
inter-agent communication. Mirrors Perplexity Computer's task architecture.

Key capabilities:
- Persistent tasks survive process restarts (SQLite-backed)
- Pause/resume without losing progress
- Cron scheduling for recurring tasks
- Filesystem IPC: agents communicate via shared workspace files
- Human check-in gates for irreversible actions
- Task dependency chains (task B runs after task A completes)
- Kill switch per task or globally

Usage::

    from orchestra.tasks import TaskManager, TaskSpec, Schedule

    manager = TaskManager()

    # One-shot task
    task_id = await manager.submit(TaskSpec(
        name="Q1 Analysis",
        prompt="Analyze Q1 revenue data and create a presentation",
        model="claude-opus-4.6-openrouter",
    ))

    # Scheduled recurring task
    task_id = await manager.submit(TaskSpec(
        name="Daily News Brief",
        prompt="Research top AI news from today and email a summary",
        schedule=Schedule(cron="0 8 * * *"),  # 8am daily
    ))

    # Monitor progress
    status = await manager.get_status(task_id)
    await manager.pause(task_id)
    await manager.resume(task_id)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .router import ModelRouter

__all__ = [
    "TaskStatus",
    "TaskPriority",
    "Schedule",
    "CheckIn",
    "TaskSpec",
    "Task",
    "TaskStore",
    "FileSystemIPC",
    "TaskManager",
    "tool_task_status",
    "tool_task_submit",
    "register_task_tools",
]

log = logging.getLogger("orchestra.tasks")


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """Lifecycle states for a Task."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_FOR_INPUT = "waiting_for_input"  # human check-in requested
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SCHEDULED = "scheduled"  # waiting for cron trigger


class TaskPriority(str, Enum):
    """Execution priority levels."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


# ---------------------------------------------------------------------------
# Minimal cron parser
# ---------------------------------------------------------------------------


def _parse_cron_field(expr: str, lo: int, hi: int) -> set[int]:
    """Parse one cron field into a set of matching integers.

    Supports: ``*``, ``*/step``, ``a-b``, ``a-b/step``, comma-separated
    combinations, and plain numbers.

    Args:
        expr: The cron field string (e.g. ``"0"``, ``"*/5"``, ``"1-5,8"``).
        lo: Minimum allowed value for this field.
        hi: Maximum allowed value (inclusive).

    Returns:
        Set of integer values that match this field.
    """
    result: set[int] = set()
    for part in expr.split(","):
        part = part.strip()
        if part == "*":
            result.update(range(lo, hi + 1))
        elif part.startswith("*/"):
            step = int(part[2:])
            result.update(range(lo, hi + 1, step))
        elif "-" in part:
            range_part, *step_part = part.split("/")
            a, b = range_part.split("-")
            step = int(step_part[0]) if step_part else 1
            result.update(range(int(a), int(b) + 1, step))
        else:
            result.add(int(part))
    return result


def _cron_next_run(cron: str, after: float) -> float:
    """Calculate the next Unix timestamp for *cron* after *after*.

    Uses a minute-level search that advances at most 4 years to avoid
    infinite loops on invalid expressions.

    Args:
        cron: Standard 5-field cron expression ``"M H D Mo DOW"``.
        after: Unix timestamp to search forward from.

    Returns:
        Unix timestamp of the next matching minute.

    Raises:
        ValueError: If cron expression is not 5 fields.
    """
    fields = cron.strip().split()
    if len(fields) != 5:
        raise ValueError(f"Expected 5 cron fields, got {len(fields)}: {cron!r}")

    minutes = _parse_cron_field(fields[0], 0, 59)
    hours = _parse_cron_field(fields[1], 0, 23)
    days = _parse_cron_field(fields[2], 1, 31)
    months = _parse_cron_field(fields[3], 1, 12)
    weekdays = _parse_cron_field(fields[4], 0, 6)  # 0=Sunday

    # Start from the next full minute after `after`
    candidate = int(after) - (int(after) % 60) + 60
    max_candidate = after + 4 * 365 * 86400  # search up to 4 years

    while candidate <= max_candidate:
        dt = datetime.fromtimestamp(candidate, tz=timezone.utc)
        if (
            dt.month in months
            and dt.day in days
            and dt.weekday() in {(d - 1) % 7 for d in weekdays}  # tm_wday: Mon=0
            # convert cron DOW (0=Sun) → Python weekday (0=Mon)
            # cron 0 (Sun) → Python 6; cron 1 (Mon) → Python 0, etc.
            and dt.hour in hours
            and dt.minute in minutes
        ):
            return float(candidate)
        candidate += 60

    raise ValueError(f"No next run found for cron {cron!r} — expression may never match")


def _cron_matches_now(cron: str, window: int = 60) -> bool:
    """Return True if *cron* should fire within the current *window* seconds.

    Args:
        cron: 5-field cron expression.
        window: Tolerance window in seconds (default 60).
    """
    now = time.time()
    try:
        next_ts = _cron_next_run(cron, now - window - 1)
        return next_ts <= now + window
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Schedule:
    """Cron-style scheduling for recurring tasks.

    At most one of *cron*, *run_once_at*, or *interval_seconds* should be set.
    If multiple are set, priority order is: ``run_once_at`` > ``cron`` >
    ``interval_seconds``.
    """

    cron: str = ""
    """Standard 5-field cron expression (e.g. ``"0 8 * * *"`` for 8 AM daily)."""

    run_once_at: float = 0.0
    """Unix timestamp for a single future execution (0.0 = disabled)."""

    interval_seconds: int = 0
    """Repeat every N seconds after last completion (0 = disabled)."""

    max_runs: int = 0
    """Maximum number of executions; 0 means unlimited."""

    timezone: str = "UTC"
    """Timezone name (informational only; all calculations use UTC timestamps)."""

    # Internal run counter — incremented by TaskManager after each execution.
    _run_count: int = field(default=0, repr=False)

    def next_run(self, after: float | None = None) -> float | None:
        """Return the next scheduled Unix timestamp after *after*.

        Args:
            after: Reference timestamp (defaults to ``time.time()``).

        Returns:
            Unix timestamp of the next run, or ``None`` if no more runs are
            scheduled (e.g. *max_runs* exhausted or schedule is empty).
        """
        after = after if after is not None else time.time()

        if self.max_runs > 0 and self._run_count >= self.max_runs:
            return None

        if self.run_once_at:
            return self.run_once_at if self.run_once_at > after else None

        if self.cron:
            try:
                return _cron_next_run(self.cron, after)
            except ValueError as exc:
                log.warning("Invalid cron expression: %s", exc)
                return None

        if self.interval_seconds:
            return after + self.interval_seconds

        return None

    def matches_now(self) -> bool:
        """Return True if this schedule should fire right now (within 60 s)."""
        if self.max_runs > 0 and self._run_count >= self.max_runs:
            return False

        now = time.time()

        if self.run_once_at:
            return abs(now - self.run_once_at) <= 60

        if self.cron:
            return _cron_matches_now(self.cron)

        return False  # interval-based schedules use next_run_at stored on Task

    def to_dict(self) -> dict[str, Any]:
        return {
            "cron": self.cron,
            "run_once_at": self.run_once_at,
            "interval_seconds": self.interval_seconds,
            "max_runs": self.max_runs,
            "timezone": self.timezone,
            "_run_count": self._run_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Schedule":
        s = cls(
            cron=d.get("cron", ""),
            run_once_at=float(d.get("run_once_at", 0.0)),
            interval_seconds=int(d.get("interval_seconds", 0)),
            max_runs=int(d.get("max_runs", 0)),
            timezone=d.get("timezone", "UTC"),
        )
        s._run_count = int(d.get("_run_count", 0))
        return s


@dataclass
class CheckIn:
    """A human check-in request emitted by a running agent.

    Agents call :meth:`TaskManager.request_checkin` before executing
    irreversible operations. The task transitions to
    :attr:`TaskStatus.WAITING_FOR_INPUT` and blocks until
    :meth:`TaskManager.respond_to_checkin` is called.
    """

    task_id: str
    """ID of the parent task that raised this check-in."""

    question: str
    """The question or confirmation the agent needs answered."""

    context: str = ""
    """Additional context to help the human decide."""

    options: list[str] = field(default_factory=list)
    """Suggested response strings (may be left empty for free-form answers)."""

    required: bool = True
    """If False, the agent auto-proceeds after *timeout_seconds* with best guess."""

    timeout_seconds: int = 3600
    """How long (in seconds) to wait before auto-proceeding (if not required)."""

    created_at: float = field(default_factory=time.time)
    """Unix timestamp when the check-in was created."""

    response: str = ""
    """Human's response, written by :meth:`TaskManager.respond_to_checkin`."""

    responded_at: float = 0.0
    """Unix timestamp when the response was provided."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    """Unique identifier for this check-in."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "question": self.question,
            "context": self.context,
            "options": self.options,
            "required": self.required,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at,
            "response": self.response,
            "responded_at": self.responded_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CheckIn":
        c = cls(
            task_id=d["task_id"],
            question=d["question"],
            context=d.get("context", ""),
            options=d.get("options", []),
            required=d.get("required", True),
            timeout_seconds=int(d.get("timeout_seconds", 3600)),
            created_at=float(d.get("created_at", 0.0)),
            response=d.get("response", ""),
            responded_at=float(d.get("responded_at", 0.0)),
        )
        c.id = d.get("id", str(uuid.uuid4()))
        return c


@dataclass
class TaskSpec:
    """Specification for creating a new Task.

    Pass to :meth:`TaskManager.submit` to enqueue work.
    """

    name: str
    """Human-readable label shown in dashboards and logs."""

    prompt: str
    """The task description / instruction sent to the agent."""

    model: str = "claude-opus-4.6-openrouter"
    """Model identifier routed through :class:`~orchestra.router.ModelRouter`."""

    architecture: str = "A"
    """Which Orchestra architecture sub-graph to instantiate (``"A"``, ``"C"``, …)."""

    priority: TaskPriority = TaskPriority.NORMAL
    """Execution priority; affects scheduling order when the queue is full."""

    schedule: Schedule | None = None
    """Optional recurring schedule. ``None`` means run once immediately."""

    depends_on: list[str] = field(default_factory=list)
    """Task IDs that must reach :attr:`TaskStatus.COMPLETED` before this one starts."""

    workspace_dir: str = ""
    """Custom filesystem workspace path. Defaults to ``/tmp/horizon/{task_id}``."""

    max_iterations: int = 300
    """Maximum agent loop iterations before the task is forcibly terminated."""

    timeout_seconds: int = 3600
    """Wall-clock timeout in seconds. 0 means unlimited."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Arbitrary key/value pairs stored alongside the task."""

    tags: list[str] = field(default_factory=list)
    """Freeform tags for filtering in :meth:`TaskManager.list_tasks`."""

    skills: list[str] = field(default_factory=list)
    """Skill names to activate for this task's agent loop."""

    require_checkin_before: list[str] = field(default_factory=lambda: [
        "gmail_send",
        "slack_post",
        "github_create_issue",
    ])
    """Tool names that require a human check-in before execution."""


@dataclass
class Task:
    """A persistent, auditable record of a running or completed task.

    Created internally by :meth:`TaskManager.submit`; clients interact with
    it via :meth:`TaskManager.get_status`.
    """

    id: str
    """Unique task identifier (UUID4)."""

    name: str
    """Human-readable label."""

    prompt: str
    """The prompt/instruction given to the agent."""

    model: str
    """Model identifier used for execution."""

    status: TaskStatus
    """Current lifecycle state."""

    priority: TaskPriority
    """Scheduling priority."""

    architecture: str = "A"
    """Orchestra architecture sub-graph used."""

    schedule: Schedule | None = None
    """Recurring schedule, or ``None`` for one-shot tasks."""

    depends_on: list[str] = field(default_factory=list)
    """Task IDs that must complete before this task may start."""

    workspace_dir: str = ""
    """Path to this task's isolated filesystem workspace."""

    created_at: float = field(default_factory=time.time)
    """Unix timestamp when the task record was created."""

    started_at: float = 0.0
    """Unix timestamp when execution began (0 if not yet started)."""

    completed_at: float = 0.0
    """Unix timestamp when the task reached a terminal state."""

    paused_at: float = 0.0
    """Unix timestamp of the most recent pause."""

    next_run_at: float = 0.0
    """For scheduled tasks: when the next run should fire."""

    result: str = ""
    """Final output from the agent (set on completion)."""

    error: str = ""
    """Error description if the task failed."""

    progress_notes: list[str] = field(default_factory=list)
    """Self-reported progress notes appended by the running agent."""

    tool_calls: int = 0
    """Total number of tool calls executed so far."""

    iterations: int = 0
    """Number of agent loop iterations completed so far."""

    tags: list[str] = field(default_factory=list)
    """Freeform tags inherited from :class:`TaskSpec`."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Arbitrary key/value metadata."""

    checkins: list[CheckIn] = field(default_factory=list)
    """All check-in requests for this task (resolved and pending)."""

    max_iterations: int = 300
    """Maximum agent loop iterations before forced termination."""

    timeout_seconds: int = 3600
    """Wall-clock timeout in seconds (0 = unlimited)."""

    skills: list[str] = field(default_factory=list)
    """Skill names activated for this task."""

    # Internal: asyncio cancel handle set by TaskManager during execution.
    _cancel_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _pause_event: asyncio.Event = field(default_factory=asyncio.Event, repr=False)

    # ── Computed properties ──────────────────────────────────────────────────

    @property
    def duration_seconds(self) -> float:
        """Wall-clock duration since the task started (or total if completed)."""
        if not self.started_at:
            return 0.0
        end = self.completed_at or time.time()
        return end - self.started_at

    @property
    def is_active(self) -> bool:
        """True while the task is in a non-terminal state."""
        return self.status in (
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.PAUSED,
            TaskStatus.WAITING_FOR_INPUT,
        )

    @property
    def pending_checkin(self) -> CheckIn | None:
        """Return the first unanswered check-in, or ``None``."""
        for c in self.checkins:
            if not c.response:
                return c
        return None

    # ── Serialisation ────────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialise the task to a JSON-compatible dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "prompt": self.prompt,
            "model": self.model,
            "status": self.status.value,
            "priority": self.priority.value,
            "architecture": self.architecture,
            "schedule": self.schedule.to_dict() if self.schedule else None,
            "depends_on": self.depends_on,
            "workspace_dir": self.workspace_dir,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "paused_at": self.paused_at,
            "next_run_at": self.next_run_at,
            "result": self.result,
            "error": self.error,
            "progress_notes": self.progress_notes,
            "tool_calls": self.tool_calls,
            "iterations": self.iterations,
            "tags": self.tags,
            "metadata": self.metadata,
            "checkins": [c.to_dict() for c in self.checkins],
            "max_iterations": self.max_iterations,
            "timeout_seconds": self.timeout_seconds,
            "skills": self.skills,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Task":
        """Deserialise a task from a dictionary (e.g. loaded from SQLite)."""
        schedule = Schedule.from_dict(d["schedule"]) if d.get("schedule") else None
        checkins = [CheckIn.from_dict(c) for c in d.get("checkins", [])]
        task = cls(
            id=d["id"],
            name=d["name"],
            prompt=d["prompt"],
            model=d["model"],
            status=TaskStatus(d["status"]),
            priority=TaskPriority(d["priority"]),
            architecture=d.get("architecture", "A"),
            schedule=schedule,
            depends_on=d.get("depends_on", []),
            workspace_dir=d.get("workspace_dir", ""),
            created_at=float(d.get("created_at", 0.0)),
            started_at=float(d.get("started_at", 0.0)),
            completed_at=float(d.get("completed_at", 0.0)),
            paused_at=float(d.get("paused_at", 0.0)),
            next_run_at=float(d.get("next_run_at", 0.0)),
            result=d.get("result", ""),
            error=d.get("error", ""),
            progress_notes=d.get("progress_notes", []),
            tool_calls=int(d.get("tool_calls", 0)),
            iterations=int(d.get("iterations", 0)),
            tags=d.get("tags", []),
            metadata=d.get("metadata", {}),
            checkins=checkins,
            max_iterations=int(d.get("max_iterations", 300)),
            timeout_seconds=int(d.get("timeout_seconds", 3600)),
            skills=d.get("skills", []),
        )
        return task


# ---------------------------------------------------------------------------
# SQLite task store
# ---------------------------------------------------------------------------


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL,
    priority    TEXT NOT NULL DEFAULT 'normal',
    created_at  REAL NOT NULL,
    next_run_at REAL NOT NULL DEFAULT 0,
    tags        TEXT NOT NULL DEFAULT '[]',
    data        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON tasks (next_run_at);
"""


class TaskStore:
    """SQLite-backed persistent task storage.

    All async methods delegate synchronous SQLite calls to a thread-pool
    executor so they remain non-blocking inside an asyncio event loop.

    Args:
        db_path: Path to the SQLite file. Defaults to
            ``~/.horizon/tasks.db``.
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            default_dir = Path.home() / ".horizon"
            default_dir.mkdir(parents=True, exist_ok=True)
            db_path = default_dir / "tasks.db"
        self._db_path = Path(db_path)
        self._lock = asyncio.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_schema(self) -> None:
        """Create tables and indexes if they do not already exist."""
        conn = self._connect()
        try:
            conn.executescript(_SCHEMA)
        finally:
            conn.close()

    # ── Internal helpers ────────────────────────────────────────────────────

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        data = json.loads(row["data"])
        return Task.from_dict(data)

    # ── Public async API ────────────────────────────────────────────────────

    async def save(self, task: Task) -> None:
        """Upsert a task record.

        Args:
            task: The :class:`Task` instance to persist.
        """
        data_json = json.dumps(task.to_dict())
        tags_json = json.dumps(task.tags)

        async with self._lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._sync_save,
                task.id,
                task.name,
                task.status.value,
                task.priority.value,
                task.created_at,
                task.next_run_at,
                tags_json,
                data_json,
            )

    def _sync_save(
        self,
        task_id: str,
        name: str,
        status: str,
        priority: str,
        created_at: float,
        next_run_at: float,
        tags_json: str,
        data_json: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO tasks
                   (id, name, status, priority, created_at, next_run_at, tags, data)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (task_id, name, status, priority, created_at, next_run_at, tags_json, data_json),
            )

    async def load(self, task_id: str) -> Task | None:
        """Load a task by its ID.

        Args:
            task_id: UUID of the task to retrieve.

        Returns:
            :class:`Task` or ``None`` if not found.
        """
        loop = asyncio.get_running_loop()
        row = await loop.run_in_executor(None, self._sync_load, task_id)
        if row is None:
            return None
        return self._row_to_task(row)

    def _sync_load(self, task_id: str) -> sqlite3.Row | None:
        with self._connect() as conn:
            return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    async def list_tasks(
        self,
        status: TaskStatus | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
    ) -> list[Task]:
        """List tasks with optional filtering.

        Args:
            status: If provided, only return tasks with this status.
            tags: If provided, only return tasks that have *all* of these tags.
            limit: Maximum number of results.

        Returns:
            List of :class:`Task` objects ordered by ``created_at`` descending.
        """
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(
            None, self._sync_list, status.value if status else None, limit
        )
        tasks = [self._row_to_task(r) for r in rows]
        if tags:
            tag_set = set(tags)
            tasks = [t for t in tasks if tag_set.issubset(set(t.tags))]
        return tasks

    def _sync_list(self, status: str | None, limit: int) -> list[sqlite3.Row]:
        with self._connect() as conn:
            if status:
                return conn.execute(
                    "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            return conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()

    async def delete(self, task_id: str) -> bool:
        """Delete a task record.

        Args:
            task_id: UUID of the task to delete.

        Returns:
            ``True`` if a row was deleted, ``False`` if not found.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_delete, task_id)

    def _sync_delete(self, task_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cur.rowcount > 0

    async def update_status(self, task_id: str, status: TaskStatus) -> None:
        """Update only the status column (and reflected data JSON) for a task.

        Args:
            task_id: UUID of the task.
            status: New :class:`TaskStatus` value.
        """
        task = await self.load(task_id)
        if task is None:
            return
        task.status = status
        await self.save(task)

    async def append_progress(self, task_id: str, note: str) -> None:
        """Append a progress note to an existing task's ``progress_notes``.

        Args:
            task_id: UUID of the target task.
            note: Free-form progress string from the running agent.
        """
        task = await self.load(task_id)
        if task is None:
            return
        ts = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        task.progress_notes.append(f"[{ts}] {note}")
        await self.save(task)

    async def save_checkin(self, task_id: str, checkin: CheckIn) -> None:
        """Attach a :class:`CheckIn` to an existing task record.

        Args:
            task_id: UUID of the task.
            checkin: The new check-in object.
        """
        task = await self.load(task_id)
        if task is None:
            log.warning("save_checkin: task %s not found", task_id)
            return
        task.checkins.append(checkin)
        task.status = TaskStatus.WAITING_FOR_INPUT
        await self.save(task)

    async def resolve_checkin(
        self, task_id: str, checkin_id: str, response: str
    ) -> None:
        """Record a human's response to a check-in.

        Args:
            task_id: UUID of the parent task.
            checkin_id: UUID of the :class:`CheckIn` to resolve.
            response: The human's answer.
        """
        task = await self.load(task_id)
        if task is None:
            return
        for c in task.checkins:
            if c.id == checkin_id:
                c.response = response
                c.responded_at = time.time()
                break
        # Resume task if this was the only pending check-in
        if not any(c for c in task.checkins if not c.response):
            task.status = TaskStatus.RUNNING
        await self.save(task)

    async def get_scheduled_due(self) -> list[Task]:
        """Return all tasks whose ``next_run_at`` is due (≤ now).

        Returns:
            List of :class:`Task` objects ready to be triggered.
        """
        now = time.time()
        loop = asyncio.get_running_loop()
        rows = await loop.run_in_executor(None, self._sync_get_scheduled_due, now)
        return [self._row_to_task(r) for r in rows]

    def _sync_get_scheduled_due(self, now: float) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """SELECT * FROM tasks
                   WHERE status = 'scheduled' AND next_run_at > 0 AND next_run_at <= ?
                   ORDER BY next_run_at ASC""",
                (now,),
            ).fetchall()


# ---------------------------------------------------------------------------
# Filesystem IPC
# ---------------------------------------------------------------------------


class FileSystemIPC:
    """Filesystem-based inter-process communication for sub-agents.

    Based on Perplexity's architecture: agents communicate via shared
    workspace files. This is inspectable, logged, and debuggable.

    File layout::

        /workspace/{task_id}/
            context.md              parent agent's goal and context
            agents/
                {agent_id}/
                    task.md         this sub-agent's assignment
                    output.md       this sub-agent's result (written when done)
                    status.json     current status and progress
            results/
                synthesis.md        parent's final synthesis
            logs/
                {timestamp}.log     execution log

    Args:
        workspace_root: Root directory for all task workspaces.
            Defaults to ``/tmp/horizon_workspace``.
    """

    def __init__(self, workspace_root: str | Path = "/tmp/horizon_workspace") -> None:
        self._root = Path(workspace_root)
        self._root.mkdir(parents=True, exist_ok=True)

    def _task_dir(self, task_id: str) -> Path:
        return self._root / task_id

    def create_task_workspace(self, task_id: str) -> Path:
        """Create the directory tree for a task and return its root path.

        Args:
            task_id: Task UUID.

        Returns:
            :class:`~pathlib.Path` of the task workspace root.
        """
        task_dir = self._task_dir(task_id)
        for sub in ("agents", "results", "logs"):
            (task_dir / sub).mkdir(parents=True, exist_ok=True)
        log.debug("Created workspace for task %s at %s", task_id, task_dir)
        return task_dir

    def write_context(self, task_id: str, context: str) -> None:
        """Write the parent agent's goal/context to ``context.md``.

        Args:
            task_id: Task UUID.
            context: Markdown content describing the task goal.
        """
        (self._task_dir(task_id) / "context.md").write_text(context, encoding="utf-8")

    def read_context(self, task_id: str) -> str:
        """Read the task's ``context.md``.

        Args:
            task_id: Task UUID.

        Returns:
            Markdown string, or empty string if the file does not exist.
        """
        p = self._task_dir(task_id) / "context.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def write_agent_output(self, task_id: str, agent_id: str, output: str) -> None:
        """Write a sub-agent's result to ``agents/{agent_id}/output.md``.

        Args:
            task_id: Parent task UUID.
            agent_id: Identifier for the sub-agent.
            output: Markdown output produced by the sub-agent.
        """
        agent_dir = self._task_dir(task_id) / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "output.md").write_text(output, encoding="utf-8")

    def read_agent_output(self, task_id: str, agent_id: str) -> str:
        """Read a specific sub-agent's output.

        Args:
            task_id: Parent task UUID.
            agent_id: Sub-agent identifier.

        Returns:
            Output string, or empty string if not yet written.
        """
        p = self._task_dir(task_id) / "agents" / agent_id / "output.md"
        return p.read_text(encoding="utf-8") if p.exists() else ""

    def list_agent_outputs(self, task_id: str) -> dict[str, str]:
        """Return a mapping of ``{agent_id: output}`` for all finished sub-agents.

        Args:
            task_id: Parent task UUID.

        Returns:
            Dict mapping agent IDs to their output strings.
        """
        agents_dir = self._task_dir(task_id) / "agents"
        results: dict[str, str] = {}
        if not agents_dir.exists():
            return results
        for agent_dir in agents_dir.iterdir():
            out_file = agent_dir / "output.md"
            if out_file.exists():
                results[agent_dir.name] = out_file.read_text(encoding="utf-8")
        return results

    def write_agent_status(
        self, task_id: str, agent_id: str, status: dict[str, Any]
    ) -> None:
        """Write a sub-agent's current status JSON.

        Args:
            task_id: Parent task UUID.
            agent_id: Sub-agent identifier.
            status: Dict with keys like ``"state"``, ``"progress"``, etc.
        """
        agent_dir = self._task_dir(task_id) / "agents" / agent_id
        agent_dir.mkdir(parents=True, exist_ok=True)
        (agent_dir / "status.json").write_text(
            json.dumps({**status, "updated_at": time.time()}, indent=2),
            encoding="utf-8",
        )

    def read_all_outputs(self, task_id: str) -> str:
        """Concatenate all sub-agent outputs into a single string for synthesis.

        Args:
            task_id: Parent task UUID.

        Returns:
            Markdown string with each agent's output preceded by a header.
        """
        parts: list[str] = []
        for agent_id, output in sorted(self.list_agent_outputs(task_id).items()):
            parts.append(f"## Agent: {agent_id}\n\n{output}")
        return "\n\n---\n\n".join(parts)

    def write_synthesis(self, task_id: str, synthesis: str) -> None:
        """Write the parent agent's final synthesis to ``results/synthesis.md``.

        Args:
            task_id: Parent task UUID.
            synthesis: Markdown synthesis produced by the orchestrator.
        """
        results_dir = self._task_dir(task_id) / "results"
        results_dir.mkdir(parents=True, exist_ok=True)
        (results_dir / "synthesis.md").write_text(synthesis, encoding="utf-8")

    def append_log(self, task_id: str, message: str) -> None:
        """Append a timestamped message to today's log file.

        Args:
            task_id: Parent task UUID.
            message: Log line to append.
        """
        logs_dir = self._task_dir(task_id) / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        ts_file = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        log_file = logs_dir / f"{ts_file}.log"
        ts = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(f"[{ts}] {message}\n")

    def cleanup_workspace(self, task_id: str) -> None:
        """Remove the entire workspace directory for a task.

        Args:
            task_id: Parent task UUID.

        .. warning::
            This is irreversible.  Only call after confirming the task result
            has been persisted elsewhere.
        """
        task_dir = self._task_dir(task_id)
        if task_dir.exists():
            shutil.rmtree(task_dir, ignore_errors=True)
            log.info("Cleaned up workspace for task %s", task_id)

    def get_workspace_summary(self, task_id: str) -> dict[str, Any]:
        """Return a summary dict describing workspace contents.

        Args:
            task_id: Parent task UUID.

        Returns:
            Dict with keys ``task_id``, ``exists``, ``agents``, ``has_synthesis``,
            ``log_files``, ``total_size_bytes``.
        """
        task_dir = self._task_dir(task_id)
        if not task_dir.exists():
            return {"task_id": task_id, "exists": False}

        agents: list[str] = []
        agents_dir = task_dir / "agents"
        if agents_dir.exists():
            agents = [d.name for d in agents_dir.iterdir() if d.is_dir()]

        log_files: list[str] = []
        logs_dir = task_dir / "logs"
        if logs_dir.exists():
            log_files = [f.name for f in logs_dir.iterdir() if f.is_file()]

        total_bytes = sum(f.stat().st_size for f in task_dir.rglob("*") if f.is_file())

        return {
            "task_id": task_id,
            "exists": True,
            "agents": agents,
            "has_synthesis": (task_dir / "results" / "synthesis.md").exists(),
            "log_files": log_files,
            "total_size_bytes": total_bytes,
        }


# ---------------------------------------------------------------------------
# Task manager
# ---------------------------------------------------------------------------


class TaskManager:
    """Manage persistent, schedulable, pauseable Orchestra tasks.

    The :class:`TaskManager` is the primary entry point for submitting and
    controlling long-running agentic work.  It wraps a :class:`TaskStore`
    for persistence and a :class:`FileSystemIPC` instance for inter-agent
    communication.

    Args:
        store: Persistent backend; defaults to a new :class:`TaskStore`.
        router: Model router for agent execution; creates a default one if
            not provided.
        max_concurrent: Maximum number of simultaneously running tasks.
        workspace_root: Root directory for filesystem workspaces.
    """

    def __init__(
        self,
        store: TaskStore | None = None,
        router: ModelRouter | None = None,
        max_concurrent: int = 10,
        workspace_root: str = "/tmp/horizon_workspace",
    ) -> None:
        self._store = store or TaskStore()
        self._router = router or ModelRouter()
        self._max_concurrent = max_concurrent
        self._ipc = FileSystemIPC(workspace_root)
        self._lock = asyncio.Lock()
        self._running: dict[str, asyncio.Task[None]] = {}  # task_id → asyncio.Task
        self._scheduler_task: asyncio.Task[None] | None = None

    # ── Submission ───────────────────────────────────────────────────────────

    async def submit(self, spec: TaskSpec) -> str:
        """Submit a new task for execution.

        If the spec has a :class:`Schedule`, the task is persisted with
        status ``SCHEDULED`` and will be triggered by :meth:`tick`.
        Otherwise it is queued for immediate execution.

        Args:
            spec: :class:`TaskSpec` describing the desired work.

        Returns:
            The UUID string of the created :class:`Task`.
        """
        task_id = str(uuid.uuid4())
        workspace = spec.workspace_dir or f"/tmp/horizon/{task_id}"

        # Determine initial status
        if spec.schedule is not None:
            initial_status = TaskStatus.SCHEDULED
            next_run = spec.schedule.next_run() or 0.0
        else:
            initial_status = TaskStatus.PENDING
            next_run = 0.0

        task = Task(
            id=task_id,
            name=spec.name,
            prompt=spec.prompt,
            model=spec.model,
            status=initial_status,
            priority=spec.priority,
            architecture=spec.architecture,
            schedule=spec.schedule,
            depends_on=spec.depends_on,
            workspace_dir=workspace,
            next_run_at=next_run,
            tags=spec.tags,
            metadata=spec.metadata,
            max_iterations=spec.max_iterations,
            timeout_seconds=spec.timeout_seconds,
            skills=spec.skills,
        )

        await self._store.save(task)
        log.info("Submitted task %s (%s) status=%s", task_id, spec.name, initial_status.value)

        if initial_status == TaskStatus.PENDING:
            asyncio.create_task(self._maybe_start(task))  # noqa: RUF006

        return task_id

    async def submit_batch(self, specs: list[TaskSpec]) -> list[str]:
        """Submit multiple tasks concurrently.

        Args:
            specs: List of :class:`TaskSpec` instances.

        Returns:
            Ordered list of task UUIDs matching the input order.
        """
        results = await asyncio.gather(*[self.submit(s) for s in specs])
        return list(results)

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def pause(self, task_id: str) -> bool:
        """Pause a running task.

        The running asyncio coroutine checks for the pause event between
        iterations and will suspend itself at the next checkpoint.

        Args:
            task_id: UUID of the task to pause.

        Returns:
            ``True`` on success, ``False`` if the task was not found or is
            not in a pauseable state.
        """
        task = await self._store.load(task_id)
        if task is None or task.status != TaskStatus.RUNNING:
            return False
        task.status = TaskStatus.PAUSED
        task.paused_at = time.time()
        await self._store.save(task)
        # Signal the running coroutine
        async with self._lock:
            at = self._running.get(task_id)
        if at:
            at.cancel()  # the _execute wrapper handles cancellation gracefully
        log.info("Paused task %s", task_id)
        return True

    async def resume(self, task_id: str) -> bool:
        """Resume a paused task.

        Re-enqueues the task for execution.  Progress notes and intermediate
        state are preserved in the :class:`TaskStore`.

        Args:
            task_id: UUID of the task to resume.

        Returns:
            ``True`` on success, ``False`` if not found or not paused.
        """
        task = await self._store.load(task_id)
        if task is None or task.status != TaskStatus.PAUSED:
            return False
        task.status = TaskStatus.PENDING
        await self._store.save(task)
        asyncio.create_task(self._maybe_start(task))  # noqa: RUF006
        log.info("Resuming task %s", task_id)
        return True

    async def cancel(self, task_id: str) -> bool:
        """Cancel a task regardless of its current state.

        Args:
            task_id: UUID of the task to cancel.

        Returns:
            ``True`` on success, ``False`` if not found.
        """
        task = await self._store.load(task_id)
        if task is None:
            return False
        task.status = TaskStatus.CANCELLED
        task.completed_at = time.time()
        await self._store.save(task)
        async with self._lock:
            at = self._running.pop(task_id, None)
        if at:
            at.cancel()
        log.info("Cancelled task %s", task_id)
        return True

    async def kill_all(self) -> int:
        """Cancel every active task (global kill switch).

        Returns:
            Number of tasks that were cancelled.
        """
        async with self._lock:
            ids = list(self._running.keys())
        count = 0
        for task_id in ids:
            if await self.cancel(task_id):
                count += 1
        log.warning("kill_all: cancelled %d tasks", count)
        return count

    # ── Check-ins ────────────────────────────────────────────────────────────

    async def get_pending_checkins(self) -> list[tuple[str, CheckIn]]:
        """Return all unanswered check-ins across all tasks.

        Returns:
            List of ``(task_id, CheckIn)`` tuples.
        """
        tasks = await self._store.list_tasks(status=TaskStatus.WAITING_FOR_INPUT)
        pairs: list[tuple[str, CheckIn]] = []
        for task in tasks:
            for c in task.checkins:
                if not c.response:
                    pairs.append((task.id, c))
        return pairs

    async def respond_to_checkin(
        self, task_id: str, checkin_id: str, response: str
    ) -> None:
        """Provide a human response to a pending check-in.

        After all check-ins for a task are resolved, the task status is
        automatically set back to ``RUNNING`` and execution resumes.

        Args:
            task_id: UUID of the parent task.
            checkin_id: UUID of the :class:`CheckIn` to resolve.
            response: The human's answer.
        """
        await self._store.resolve_checkin(task_id, checkin_id, response)
        log.info("Check-in %s for task %s resolved", checkin_id, task_id)

    async def request_checkin(
        self,
        task_id: str,
        question: str,
        options: list[str] | None = None,
        context: str = "",
        required: bool = True,
        timeout_seconds: int = 3600,
    ) -> str:
        """Create a check-in request and block the task until it is answered.

        This is called by *agent-callable* tool implementations.  It persists
        the :class:`CheckIn`, transitions the task to
        ``WAITING_FOR_INPUT``, and returns the checkin ID so callers can poll
        :meth:`respond_to_checkin`.

        Args:
            task_id: UUID of the requesting task.
            question: The question the agent needs answered.
            options: Suggested response strings (optional).
            context: Additional background for the human reviewer.
            required: If ``False``, agent auto-proceeds after timeout.
            timeout_seconds: How long to wait before auto-proceeding.

        Returns:
            The UUID of the new :class:`CheckIn`.
        """
        checkin = CheckIn(
            task_id=task_id,
            question=question,
            context=context,
            options=options or [],
            required=required,
            timeout_seconds=timeout_seconds,
        )
        await self._store.save_checkin(task_id, checkin)
        self._ipc.append_log(
            task_id, f"CHECK-IN requested: {question} (id={checkin.id})"
        )
        return checkin.id

    # ── Status & Results ─────────────────────────────────────────────────────

    async def get_status(self, task_id: str) -> Task | None:
        """Return the full :class:`Task` record for *task_id*.

        Args:
            task_id: UUID of the task.

        Returns:
            :class:`Task` or ``None`` if not found.
        """
        return await self._store.load(task_id)

    async def get_result(self, task_id: str) -> str:
        """Return the final result string for a completed task.

        Args:
            task_id: Task UUID.

        Returns:
            Result string, or empty string if task is not yet complete.
        """
        task = await self._store.load(task_id)
        if task is None:
            return ""
        return task.result

    async def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """Return tasks, optionally filtered by status.

        Args:
            status: Optional status filter.

        Returns:
            List of :class:`Task` objects ordered by creation time (newest first).
        """
        return await self._store.list_tasks(status=status)

    async def get_workspace(self, task_id: str) -> dict[str, Any]:
        """Return the filesystem workspace summary for a task.

        Args:
            task_id: Task UUID.

        Returns:
            Dict from :meth:`FileSystemIPC.get_workspace_summary`.
        """
        return self._ipc.get_workspace_summary(task_id)

    # ── Scheduling ───────────────────────────────────────────────────────────

    async def tick(self) -> int:
        """Check for due scheduled tasks and enqueue them.

        Called periodically by :meth:`start_scheduler`.  Also safe to call
        manually in tests.

        Returns:
            Number of tasks that were triggered this tick.
        """
        due = await self._store.get_scheduled_due()
        triggered = 0
        for task in due:
            task.status = TaskStatus.PENDING
            # Advance schedule for recurring tasks
            if task.schedule:
                task.schedule._run_count += 1
                nxt = task.schedule.next_run()
                task.next_run_at = nxt if nxt else 0.0
            await self._store.save(task)
            asyncio.create_task(self._maybe_start(task))  # noqa: RUF006
            triggered += 1
            log.info("Scheduler triggered task %s (%s)", task.id, task.name)
        return triggered

    async def start_scheduler(self, interval_seconds: int = 60) -> None:
        """Start a background scheduler loop.

        Calls :meth:`tick` every *interval_seconds* seconds until
        :meth:`stop_scheduler` is called.

        Args:
            interval_seconds: Polling interval in seconds (default 60).
        """
        if self._scheduler_task and not self._scheduler_task.done():
            log.warning("Scheduler already running")
            return

        async def _loop() -> None:
            log.info("Scheduler started (interval=%ds)", interval_seconds)
            while True:
                try:
                    await self.tick()
                except Exception as exc:
                    log.exception("Scheduler tick error: %s", exc)
                await asyncio.sleep(interval_seconds)

        self._scheduler_task = asyncio.create_task(_loop())

    async def stop_scheduler(self) -> None:
        """Stop the background scheduler loop."""
        if self._scheduler_task and not self._scheduler_task.done():
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
            log.info("Scheduler stopped")

    # ── Internal ─────────────────────────────────────────────────────────────

    async def _maybe_start(self, task: Task) -> None:
        """Start a task if concurrency limits and dependencies allow.

        Args:
            task: The :class:`Task` to (possibly) start.
        """
        async with self._lock:
            if len(self._running) >= self._max_concurrent:
                log.debug(
                    "Concurrency limit hit (%d/%d); task %s queued",
                    len(self._running),
                    self._max_concurrent,
                    task.id,
                )
                return
            if not await self._check_dependencies(task):
                log.debug("Task %s waiting on dependencies", task.id)
                return
            coro = self._execute(task)
            at = asyncio.create_task(coro)
            self._running[task.id] = at

        def _on_done(fut: asyncio.Future[None]) -> None:
            asyncio.create_task(self._on_task_done(task.id, fut))  # noqa: RUF006

        at.add_done_callback(_on_done)

    async def _on_task_done(self, task_id: str, fut: asyncio.Future[None]) -> None:
        """Clean up after a task asyncio future completes."""
        async with self._lock:
            self._running.pop(task_id, None)
        if fut.cancelled():
            log.debug("Task %s asyncio future was cancelled", task_id)

    async def _check_dependencies(self, task: Task) -> bool:
        """Return True if all ``task.depends_on`` tasks have completed.

        Args:
            task: The task whose dependencies to verify.

        Returns:
            ``True`` if all dependencies are complete (or there are none).
        """
        for dep_id in task.depends_on:
            dep = await self._store.load(dep_id)
            if dep is None or dep.status != TaskStatus.COMPLETED:
                return False
        return True

    async def _execute(self, task: Task) -> None:
        """Run the agent loop for *task* and update the store accordingly.

        This is the core execution method.  It:

        1. Creates a filesystem workspace.
        2. Writes ``context.md`` for sub-agents.
        3. Runs the :class:`~orchestra.agent_loop.AgentLoop`.
        4. Persists progress notes, tool-call counts, and the final result.
        5. Handles pause/cancel via asyncio cancellation.

        Args:
            task: The :class:`Task` to execute.
        """
        # Import here to avoid circular imports at module level
        from .agent_loop import AgentLoop, AgentConfig, create_default_tools
        from .agent_loop import (
            FinalAnswerEvent,
            ErrorEvent,
            ToolCallEvent,
            ToolResultEvent,
            ThinkingEvent,
        )

        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or time.time()
        await self._store.save(task)

        # Set up filesystem workspace
        self._ipc.create_task_workspace(task.id)
        self._ipc.write_context(task.id, f"# Task: {task.name}\n\n{task.prompt}")
        self._ipc.append_log(task.id, f"Task started (model={task.model})")

        config = AgentConfig(
            model=task.model,
            max_iterations=task.max_iterations,
        )
        tools = create_default_tools(self._router)
        loop = AgentLoop(router=self._router, tools=tools, config=config)

        try:
            timeout: float | None = (
                float(task.timeout_seconds) if task.timeout_seconds else None
            )

            async def _run() -> None:
                nonlocal task
                tool_calls = 0
                iterations = 0
                async for event in loop.run(task.prompt):
                    if isinstance(event, ToolCallEvent):
                        tool_calls += 1
                        self._ipc.append_log(
                            task.id,
                            f"Tool call [{event.iteration}]: {event.tool_name}",
                        )
                    elif isinstance(event, ToolResultEvent):
                        iterations = event.iteration
                    elif isinstance(event, ThinkingEvent):
                        # Self-reported progress: capture first 200 chars as a note
                        note = event.content[:200].replace("\n", " ")
                        if note:
                            task.progress_notes.append(note)
                    elif isinstance(event, FinalAnswerEvent):
                        task.result = event.content
                        task.tool_calls = event.total_tool_calls
                        task.iterations = event.total_iterations
                        task.status = TaskStatus.COMPLETED
                        task.completed_at = time.time()
                        await self._store.save(task)
                        self._ipc.write_synthesis(task.id, task.result)
                        self._ipc.append_log(
                            task.id,
                            f"Completed after {event.total_iterations} iterations, "
                            f"{event.total_tool_calls} tool calls.",
                        )
                        return
                    elif isinstance(event, ErrorEvent):
                        if not event.recoverable:
                            raise RuntimeError(event.message)
                        log.warning("Recoverable error in task %s: %s", task.id, event.message)

                # If we exhausted the loop without a FinalAnswerEvent
                task.status = TaskStatus.FAILED
                task.error = "Max iterations reached without final answer."
                task.completed_at = time.time()
                await self._store.save(task)

            if timeout:
                await asyncio.wait_for(_run(), timeout=timeout)
            else:
                await _run()

        except asyncio.CancelledError:
            # Distinguish pause vs. cancel based on persisted status
            current = await self._store.load(task.id)
            if current and current.status == TaskStatus.PAUSED:
                log.info("Task %s paused", task.id)
            else:
                task.status = TaskStatus.CANCELLED
                task.completed_at = time.time()
                await self._store.save(task)
                log.info("Task %s cancelled", task.id)
            raise  # re-raise so asyncio cleans up the Task properly

        except asyncio.TimeoutError:
            task.status = TaskStatus.FAILED
            task.error = f"Timed out after {task.timeout_seconds}s"
            task.completed_at = time.time()
            await self._store.save(task)
            self._ipc.append_log(task.id, f"TIMEOUT after {task.timeout_seconds}s")
            log.error("Task %s timed out", task.id)

        except Exception as exc:
            task.status = TaskStatus.FAILED
            task.error = str(exc)
            task.completed_at = time.time()
            await self._store.save(task)
            self._ipc.append_log(task.id, f"FAILED: {exc}")
            log.exception("Task %s failed: %s", task.id, exc)

    # ── Stats ────────────────────────────────────────────────────────────────

    @property
    def stats(self) -> dict[str, Any]:
        """Return a snapshot of current manager statistics.

        Returns:
            Dict with ``running``, ``max_concurrent``, and
            ``scheduler_active`` keys.
        """
        return {
            "running": len(self._running),
            "max_concurrent": self._max_concurrent,
            "scheduler_active": (
                self._scheduler_task is not None
                and not self._scheduler_task.done()
            ),
        }


# ---------------------------------------------------------------------------
# Agent-callable tools
# ---------------------------------------------------------------------------

# Module-level singleton used by the agent-callable tool functions below.
# Replaced at runtime via register_task_tools().
_default_manager: TaskManager | None = None


async def tool_task_status(task_id: str) -> str:
    """Get the status and progress of a background task.

    Args:
        task_id: UUID of the task to query.

    Returns:
        JSON string with task status details.
    """
    manager = _default_manager
    if manager is None:
        return json.dumps({"error": "TaskManager not initialised"})
    task = await manager.get_status(task_id)
    if task is None:
        return json.dumps({"error": f"Task {task_id!r} not found"})
    return json.dumps({
        "id": task.id,
        "name": task.name,
        "status": task.status.value,
        "progress_notes": task.progress_notes[-10:],  # last 10 notes
        "tool_calls": task.tool_calls,
        "iterations": task.iterations,
        "duration_seconds": round(task.duration_seconds, 1),
        "result_preview": task.result[:500] if task.result else "",
        "error": task.error,
    })


async def tool_task_submit(
    prompt: str,
    model: str = "claude-opus-4.6-openrouter",
    name: str = "",
) -> str:
    """Submit a new background task and return its ID.

    Args:
        prompt: The task description to execute.
        model: Model identifier (defaults to claude-opus-4.6-openrouter).
        name: Optional human-readable task name.

    Returns:
        JSON string with ``{"task_id": "..."}`` on success.
    """
    manager = _default_manager
    if manager is None:
        return json.dumps({"error": "TaskManager not initialised"})
    spec = TaskSpec(
        name=name or prompt[:60],
        prompt=prompt,
        model=model or "claude-opus-4.6-openrouter",
    )
    task_id = await manager.submit(spec)
    return json.dumps({"task_id": task_id, "status": "pending"})


def register_task_tools(tool_registry: Any, manager: TaskManager) -> None:
    """Register task management tools into an agent's :class:`~orchestra.agent_loop.ToolRegistry`.

    Also sets the module-level ``_default_manager`` singleton used by the
    tool functions so they can be called without a direct manager reference.

    Args:
        tool_registry: A :class:`~orchestra.agent_loop.ToolRegistry` instance.
        manager: The :class:`TaskManager` to bind.
    """
    global _default_manager
    _default_manager = manager

    tool_registry.register(
        name="task_status",
        description=(
            "Get the current status, progress notes, and result preview of a "
            "background Orchestra task by its ID."
        ),
        parameters={
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "UUID of the background task to query.",
                },
            },
            "required": ["task_id"],
        },
        handler=tool_task_status,
    )

    tool_registry.register(
        name="task_submit",
        description=(
            "Submit a new long-running background task to Orchestra. "
            "Returns the task ID immediately; use task_status to monitor progress."
        ),
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Full description of the task for the agent to execute.",
                },
                "model": {
                    "type": "string",
                    "description": "Model to use (default: claude-opus-4.6-openrouter).",
                },
                "name": {
                    "type": "string",
                    "description": "Short human-readable task name (optional).",
                },
            },
            "required": ["prompt"],
        },
        handler=tool_task_submit,
    )

    log.info("Task tools registered (task_status, task_submit)")
