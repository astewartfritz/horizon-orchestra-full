from __future__ import annotations

"""WorkflowRunner — ties together the job queue, checkpoints, and timers.

This is the "orchestration engine" layer described in the agentic workflow
stack architecture: guaranteed retries (via Worker), durable state (via
CheckpointStore), and long-run timers (via TimerStore / WorkflowSuspended).

Usage::

    from orchestra.queue.runner import WorkflowRunner

    runner = WorkflowRunner()
    runner.register("run_agent", my_async_handler)
    await runner.start()           # starts workers + timer-poll loop
    wf_id = await runner.submit("run_agent", {"goal": "..."})
    await runner.wait(wf_id)
    await runner.stop()
"""

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from .checkpoint import CheckpointStore
from .job import Job
from .queue import JobQueue
from .timer import TimerStore, WorkflowSuspended
from .worker import Worker

log = logging.getLogger("orchestra.queue.runner")

_TIMER_POLL = 10  # seconds between timer-due checks


class WorkflowRunner:
    """High-level runner: submit → execute → checkpoint → resume on restart."""

    def __init__(
        self,
        concurrency: int = 4,
        checkpoint_store: CheckpointStore | None = None,
        timer_store: TimerStore | None = None,
    ) -> None:
        self._queue = JobQueue.memory()
        self._checkpoints = checkpoint_store or CheckpointStore()
        self._timers = timer_store or TimerStore()
        self._handlers: dict[str, Callable[[Job], Awaitable[dict]]] = {}
        self._worker = Worker(
            self._queue,
            handler=self._dispatch,
            concurrency=concurrency,
            name="wf-worker",
        )
        self._running = False
        self._timer_task: asyncio.Task | None = None

    # ------------------------------------------------------------------
    def register(self, name: str, handler: Callable[[Job], Awaitable[dict]]) -> None:
        """Register a job handler by name."""
        self._handlers[name] = handler

    async def submit(
        self,
        name: str,
        payload: dict[str, Any],
        priority: int = 5,
    ) -> str:
        job = Job.new(name=name, payload=payload, priority=priority)
        await self._queue._enqueue(job)
        log.info("submitted job %s (%s)", job.id, name)
        return job.id

    async def start(self) -> None:
        self._running = True
        await self._worker.start()
        self._timer_task = asyncio.create_task(self._timer_loop(), name="wf-timer")
        # Re-queue any suspended workflows whose timers have elapsed
        await self._resume_due_timers()
        log.info("WorkflowRunner started")

    async def stop(self) -> None:
        self._running = False
        await self._worker.stop()
        if self._timer_task:
            self._timer_task.cancel()
        log.info("WorkflowRunner stopped")

    # ------------------------------------------------------------------
    async def _dispatch(self, job: Job) -> dict:
        handler = self._handlers.get(job.name)
        if handler is None:
            raise ValueError(f"no handler registered for '{job.name}'")
        try:
            return await handler(job)
        except WorkflowSuspended as ws:
            # Workflow asked for a durable sleep — not a failure
            self._timers.set(ws.workflow_id, ws.resume_at)
            log.info("workflow %s suspended until %.0f", ws.workflow_id, ws.resume_at)
            return {"status": "suspended", "resume_at": ws.resume_at}

    async def _timer_loop(self) -> None:
        while self._running:
            await asyncio.sleep(_TIMER_POLL)
            await self._resume_due_timers()

    async def _resume_due_timers(self) -> None:
        for wid in self._timers.due():
            cp = self._checkpoints.load(wid)
            if cp is None:
                self._timers.clear(wid)
                continue
            log.info("re-queuing workflow %s (timer elapsed)", wid)
            job = Job.new(
                name=cp.goal[:50],   # job name is the first 50 chars of goal
                payload={"workflow_id": wid, "goal": cp.goal},
            )
            await self._queue._enqueue(job)
            self._timers.clear(wid)
