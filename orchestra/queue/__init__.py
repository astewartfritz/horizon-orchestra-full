from __future__ import annotations

"""Distributed-capable job queue for Horizon Orchestra.

Usage::

    from orchestra.queue import get_queue, Worker

    q = get_queue()                        # in-process MemoryBackend
    job = await q.submit("resize", {"url": "..."}, priority=3)

    async def handler(job):
        return {"done": True}

    worker = Worker(q, handler, concurrency=4)
    await worker.start()
"""

from .job import Job
from .queue import JobQueue
from .worker import Worker
from .checkpoint import CheckpointStore, WorkflowCheckpoint
from .timer import TimerStore, WorkflowSuspended, workflow_sleep
from .runner import WorkflowRunner

__all__ = [
    "Job",
    "JobQueue",
    "Worker",
    "CheckpointStore",
    "WorkflowCheckpoint",
    "TimerStore",
    "WorkflowSuspended",
    "workflow_sleep",
    "WorkflowRunner",
    "get_queue",
    "set_queue",
]

_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    """Return the module-level singleton queue, creating a MemoryBackend if needed."""
    global _queue
    if _queue is None:
        _queue = JobQueue.memory()
    return _queue


def set_queue(q: JobQueue) -> None:
    """Replace the module-level singleton queue."""
    global _queue
    _queue = q
