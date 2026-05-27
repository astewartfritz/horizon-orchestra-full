from __future__ import annotations

"""High-level JobQueue facade over a QueueBackend."""

from typing import Any

from .backend import MemoryBackend, QueueBackend, RedisBackend
from .job import Job


class JobQueue:
    """Submit, query, and cancel jobs backed by any QueueBackend."""

    def __init__(self, backend: QueueBackend) -> None:
        self._backend = backend

    @classmethod
    def memory(cls) -> "JobQueue":
        """Create a queue backed by the in-process MemoryBackend."""
        return cls(MemoryBackend())

    @classmethod
    async def redis(cls, dsn: str) -> "JobQueue":
        """Create a queue backed by a Redis server at *dsn*."""
        backend = await RedisBackend.connect(dsn)
        return cls(backend)

    async def submit(
        self,
        name: str,
        payload: dict[str, Any],
        priority: int = 5,
        max_retries: int = 3,
    ) -> Job:
        """Create and enqueue a new job; return the Job object."""
        job = Job.new(name, payload, priority=priority, max_retries=max_retries)
        await self._backend.enqueue(job)
        return job

    async def get(self, job_id: str) -> Job | None:
        """Return a job by ID, or None if not found."""
        return await self._backend.get(job_id)

    async def list(
        self,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Job]:
        """Return jobs, optionally filtered by status, up to *limit*."""
        return await self._backend.list_jobs(status=status, limit=limit)

    async def cancel(self, job_id: str) -> bool:
        """Cancel a pending job; return True if it existed and was removed."""
        job = await self._backend.get(job_id)
        if job is None:
            return False
        if job.status not in ("pending",):
            return False
        return await self._backend.remove(job_id)

    # Internal: used by WorkflowRunner / Worker
    async def _enqueue(self, job: Job) -> None:
        """Persist an already-constructed Job object directly."""
        await self._backend.enqueue(job)

    async def _dequeue(self) -> Job | None:
        """Pop the next available job from the backend."""
        return await self._backend.dequeue()

    async def _update(self, job: Job) -> None:
        """Persist updated job state to the backend."""
        await self._backend.update(job)

    async def _reenqueue(self, job: Job) -> None:
        """Re-add a job to the backend queue for retry."""
        await self._backend.enqueue(job)

    async def close(self) -> None:
        """Close the underlying backend."""
        await self._backend.close()
