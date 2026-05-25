from __future__ import annotations

"""Durable workflow timer.

workflow_sleep() suspends a running workflow by writing a wake-up record
to disk and raising WorkflowSuspended.  The caller (typically the CLI or
a queue worker) catches the exception, stores the workflow_id, and
re-submits the job after the delay has elapsed.

This is the lightweight alternative to Temporal's durable timers: no
extra service required, works with the existing CheckpointStore.

Usage inside a KernelConfig-equipped workflow::

    from orchestra.queue.timer import workflow_sleep, WorkflowSuspended

    try:
        await workflow_sleep(workflow_id="wf-123", seconds=3600)
    except WorkflowSuspended as ws:
        # the caller handles re-scheduling; this code never executes
        pass
"""

import asyncio
import json
import logging
import time
from pathlib import Path
import os

__all__ = ["WorkflowSuspended", "workflow_sleep", "TimerStore"]

log = logging.getLogger("orchestra.queue.timer")

_DEFAULT_DIR = Path(os.getenv("ORCHESTRA_CHECKPOINT_DIR", ".orchestra_checkpoints"))


class WorkflowSuspended(Exception):
    """Raised when a workflow suspends itself for a durable timer."""

    def __init__(self, workflow_id: str, resume_at: float) -> None:
        self.workflow_id = workflow_id
        self.resume_at = resume_at
        super().__init__(f"workflow {workflow_id} suspended until {resume_at:.0f}")


class TimerStore:
    """Persist and query pending timers."""

    def __init__(self, directory: Path | str = _DEFAULT_DIR) -> None:
        self._path = Path(directory) / "timers.json"
        Path(directory).mkdir(parents=True, exist_ok=True)

    def _load(self) -> dict[str, float]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except Exception:
                pass
        return {}

    def _save(self, data: dict[str, float]) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self._path)

    def set(self, workflow_id: str, resume_at: float) -> None:
        data = self._load()
        data[workflow_id] = resume_at
        self._save(data)

    def clear(self, workflow_id: str) -> None:
        data = self._load()
        data.pop(workflow_id, None)
        self._save(data)

    def due(self) -> list[str]:
        """Return workflow_ids whose timers have elapsed."""
        now = time.time()
        return [wid for wid, ts in self._load().items() if ts <= now]


_default_store: TimerStore | None = None


def _get_store() -> TimerStore:
    global _default_store
    if _default_store is None:
        _default_store = TimerStore()
    return _default_store


async def workflow_sleep(
    workflow_id: str,
    seconds: float,
    *,
    store: TimerStore | None = None,
) -> None:
    """Suspend a workflow for *seconds*.

    If seconds <= 60, falls through to a plain asyncio.sleep (no disk I/O).
    For longer delays, writes a timer record and raises WorkflowSuspended
    so the workflow can be descheduled and rescheduled by the runner.
    """
    if seconds <= 60:
        await asyncio.sleep(seconds)
        return

    ts = time.time() + seconds
    (store or _get_store()).set(workflow_id, ts)
    log.info("workflow %s suspended for %.0fs (resume_at=%.0f)", workflow_id, seconds, ts)
    raise WorkflowSuspended(workflow_id=workflow_id, resume_at=ts)
