from __future__ import annotations

"""Worker: pulls jobs from a JobQueue, executes them, and handles retries."""

import asyncio
import logging
import random
import time
from typing import Awaitable, Callable

from .job import Job
from .queue import JobQueue

logger = logging.getLogger(__name__)

_MAX_DEAD_RETRIES = 5
_POLL_INTERVAL = 0.25   # seconds between empty-queue polls
_MAX_BACKOFF   = 300    # cap retry backoff at 5 minutes


class Worker:
    """Pull jobs from queue, execute handler, handle retries and dead-letter."""

    def __init__(
        self,
        queue: JobQueue,
        handler: Callable[[Job], Awaitable[dict]],
        concurrency: int = 4,
        name: str = "worker",
    ) -> None:
        self._queue = queue
        self._handler = handler
        self._concurrency = concurrency
        self._name = name
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start *concurrency* worker coroutines."""
        self._running = True
        self._tasks = [
            asyncio.create_task(
                self._work_loop(),
                name=f"{self._name}-{i}",
            )
            for i in range(self._concurrency)
        ]
        logger.info(
            "Worker '%s' started with concurrency=%d",
            self._name,
            self._concurrency,
        )

    async def stop(self) -> None:
        """Signal workers to stop and wait for them to drain."""
        self._running = False
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        logger.info("Worker '%s' stopped.", self._name)

    async def _work_loop(self) -> None:
        """Single worker coroutine: poll → execute → ack/nack."""
        while self._running:
            job = await self._queue._dequeue()
            if job is None:
                await asyncio.sleep(_POLL_INTERVAL)
                continue

            # If this job was re-enqueued with a future retry_after timestamp,
            # put it back and yield rather than blocking this slot until the
            # backoff window opens.  Other jobs can run in the meantime.
            now = time.time()
            if job.retry_after is not None and job.retry_after > now:
                await self._queue._reenqueue(job)
                await asyncio.sleep(min(job.retry_after - now, _POLL_INTERVAL * 4))
                continue

            await self._execute(job)

    async def _execute(self, job: Job) -> None:
        """Run the handler for *job*, update status, and handle retries."""
        job.status = "running"
        job.started_at = time.time()
        await self._queue._update(job)

        t0 = time.monotonic()
        try:
            result = await self._handler(job)
            duration = time.monotonic() - t0
            job.status = "done"
            job.finished_at = time.time()
            job.result = result if isinstance(result, dict) else {"value": result}
            await self._queue._update(job)
            logger.info(
                "job_id=%s name=%s status=done duration=%.3fs",
                job.id,
                job.name,
                duration,
            )
        except Exception as exc:  # noqa: BLE001
            duration = time.monotonic() - t0
            job.retry_count += 1
            job.error = str(exc)
            job.finished_at = time.time()

            effective_max = min(job.max_retries, _MAX_DEAD_RETRIES)
            if job.retry_count >= effective_max:
                job.status = "dead"
                await self._queue._update(job)
                logger.info(
                    "job_id=%s name=%s status=dead retries=%d duration=%.3fs error=%s",
                    job.id,
                    job.name,
                    job.retry_count,
                    duration,
                    job.error,
                )
            else:
                backoff = min(2 ** job.retry_count, _MAX_BACKOFF)
                backoff *= (0.5 + random.random())  # ±50 % jitter
                # Re-enqueue immediately with a retry_after timestamp so this
                # worker slot is free to pick up other work during the backoff
                # window — no asyncio.sleep() that blocks the entire slot.
                job.status = "pending"
                job.retry_after = time.time() + backoff
                job.started_at = None
                job.finished_at = None
                await self._queue._reenqueue(job)
                logger.info(
                    "job_id=%s name=%s status=pending retry=%d/%d "
                    "retry_after=+%ds duration=%.3fs error=%s",
                    job.id,
                    job.name,
                    job.retry_count,
                    effective_max,
                    int(backoff),
                    duration,
                    job.error,
                )
