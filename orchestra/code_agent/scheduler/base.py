from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class CronExpr:
    """Simple cron expression parser (5-field: minute hour day month weekday)."""

    def __init__(self, expr: str):
        self.expr = expr.strip()
        self.fields = self.expr.split()
        if len(self.fields) != 5:
            raise ValueError(f"Expected 5 fields (minute hour day month weekday), got {len(self.fields)}: {expr}")
        self._parsed = [self._parse_field(f, i) for i, f in enumerate(self.fields)]

    @staticmethod
    def _parse_field(field: str, pos: int) -> set[int]:
        ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 6)]
        lo, hi = ranges[pos]
        values: set[int] = set()
        for part in field.split(","):
            part = part.strip()
            if part == "*":
                values.update(range(lo, hi + 1))
            elif "/" in part:
                base, step = part.split("/")
                step = int(step)
                if base == "*":
                    values.update(range(lo, hi + 1, step))
                else:
                    values.update(range(int(base), hi + 1, step))
            elif "-" in part:
                a, b = part.split("-")
                values.update(range(int(a), int(b) + 1))
            else:
                values.add(int(part))
        return values

    def next_match(self, after: datetime | None = None) -> datetime:
        dt = (after or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
        for _ in range(525600):
            # cron weekday: 0=Sun,1=Mon,...6=Sat; Python weekday: 0=Mon,...6=Sun
            cron_wday = (dt.weekday() + 1) % 7
            if (dt.minute in self._parsed[0] and dt.hour in self._parsed[1]
                    and dt.day in self._parsed[2] and dt.month in self._parsed[3]
                    and cron_wday in self._parsed[4]):
                return dt
            dt += timedelta(minutes=1)
        raise ValueError(f"No match within 1 year for cron: {self.expr}")

    def __repr__(self) -> str:
        return f"CronExpr('{self.expr}')"


@dataclass
class RetryPolicy:
    max_retries: int = 3
    base_delay_seconds: float = 5.0
    max_delay_seconds: float = 300.0
    backoff_multiplier: float = 2.0

    def delay(self, attempt: int) -> float:
        d = self.base_delay_seconds * (self.backoff_multiplier ** attempt)
        return min(d, self.max_delay_seconds)


@dataclass
class TaskDAG:
    """Dependency graph for scheduled tasks."""

    edges: dict[str, set[str]] = field(default_factory=dict)

    def add_dependency(self, task: str, depends_on: str) -> None:
        if task not in self.edges:
            self.edges[task] = set()
        self.edges[task].add(depends_on)

    def remove_dependency(self, task: str, depends_on: str) -> None:
        if task in self.edges and depends_on in self.edges[task]:
            self.edges[task].remove(depends_on)

    def get_dependencies(self, task: str) -> set[str]:
        return self.edges.get(task, set())

    def get_dependents(self, task: str) -> list[str]:
        return [t for t, deps in self.edges.items() if task in deps]

    def is_ready(self, task: str, completed: set[str]) -> bool:
        deps = self.get_dependencies(task)
        return deps.issubset(completed)

    def topological_sort(self, tasks: set[str]) -> list[str]:
        visited: set[str] = set()
        result: list[str] = []

        def dfs(node: str) -> None:
            if node in visited:
                return
            visited.add(node)
            for dep in self.get_dependencies(node):
                if dep in tasks:
                    dfs(dep)
            result.append(node)

        for t in sorted(tasks):
            dfs(t)
        return result


@dataclass
class ScheduledTask:
    name: str
    task: str
    cron: str = ""
    interval_seconds: int = 3600
    profile: str = "minimal"
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    retry_policy: RetryPolicy | None = None
    max_execution_seconds: float = 600.0
    timeout_seconds: float = 300.0
    provider: str = "ollama"

    last_run: float = 0.0
    next_run: float = 0.0
    status: TaskStatus = TaskStatus.PENDING
    run_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    last_error: str = ""

    def compute_next_run(self, after: datetime | None = None) -> float:
        if self.cron:
            try:
                expr = CronExpr(self.cron)
                dt = expr.next_match(after or datetime.now())
                self.next_run = dt.timestamp()
            except ValueError:
                self.next_run = (datetime.now() + timedelta(seconds=self.interval_seconds)).timestamp()
        else:
            self.next_run = (after or datetime.now()).timestamp() + self.interval_seconds
        return self.next_run

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "task": self.task,
            "cron": self.cron,
            "interval_seconds": self.interval_seconds,
            "profile": self.profile,
            "enabled": self.enabled,
            "tags": self.tags,
            "max_execution_seconds": self.max_execution_seconds,
            "timeout_seconds": self.timeout_seconds,
            "last_run": self.last_run,
            "next_run": self.next_run,
            "status": self.status.value,
            "run_count": self.run_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "last_error": self.last_error,
        }
        if self.retry_policy:
            d["retry_policy"] = {
                "max_retries": self.retry_policy.max_retries,
                "base_delay_seconds": self.retry_policy.base_delay_seconds,
                "max_delay_seconds": self.retry_policy.max_delay_seconds,
                "backoff_multiplier": self.retry_policy.backoff_multiplier,
            }
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScheduledTask:
        rp = d.pop("retry_policy", None)
        status_val = d.pop("status", "pending")
        task = cls(**d)
        task.status = TaskStatus(status_val)
        if rp:
            task.retry_policy = RetryPolicy(**rp)
        return task
