from __future__ import annotations

"""Queue backends: MemoryBackend (in-process), RedisBackend, and PostgresBackend."""

import asyncio
import json
import time
from typing import Any, Protocol, runtime_checkable

from .job import Job

try:
    import redis.asyncio as aioredis  # type: ignore
    _HAS_REDIS = True
except ImportError:
    _HAS_REDIS = False

try:
    import asyncpg  # type: ignore
    _HAS_ASYNCPG = True
except ImportError:
    _HAS_ASYNCPG = False


@runtime_checkable
class QueueBackend(Protocol):
    """Abstract protocol all queue backends must satisfy."""

    async def enqueue(self, job: Job) -> None:
        """Persist a job and make it available for dequeue."""
        ...

    async def dequeue(self) -> Job | None:
        """Pop and return the highest-priority pending job, or None."""
        ...

    async def update(self, job: Job) -> None:
        """Persist updated job state (status, result, error, etc.)."""
        ...

    async def get(self, job_id: str) -> Job | None:
        """Return a job by ID, or None if not found."""
        ...

    async def list_jobs(
        self, status: str | None = None, limit: int = 100
    ) -> list[Job]:
        """Return up to *limit* jobs, optionally filtered by status."""
        ...

    async def remove(self, job_id: str) -> bool:
        """Remove a job from the backend; return True if it existed."""
        ...

    async def close(self) -> None:
        """Release any held resources."""
        ...


class MemoryBackend:
    """In-process queue backed by asyncio.PriorityQueue."""

    def __init__(self) -> None:
        # PriorityQueue items: (priority, created_at, job_id)
        self._queue: asyncio.PriorityQueue[tuple[int, float, str]] = (
            asyncio.PriorityQueue()
        )
        self._jobs: dict[str, Job] = {}
        self._lock = asyncio.Lock()

    async def enqueue(self, job: Job) -> None:
        """Add a job to the priority queue."""
        async with self._lock:
            self._jobs[job.id] = job
        await self._queue.put((job.priority, job.created_at, job.id))

    async def dequeue(self) -> Job | None:
        """Pop the next pending job (non-blocking), or return None."""
        while True:
            try:
                _, _, job_id = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return None
            async with self._lock:
                job = self._jobs.get(job_id)
            if job is None or job.status != "pending":
                continue
            return job

    async def update(self, job: Job) -> None:
        """Update stored job state."""
        async with self._lock:
            self._jobs[job.id] = job

    async def get(self, job_id: str) -> Job | None:
        """Return a job by ID."""
        async with self._lock:
            return self._jobs.get(job_id)

    async def list_jobs(
        self, status: str | None = None, limit: int = 100
    ) -> list[Job]:
        """Return jobs, optionally filtered by status."""
        async with self._lock:
            jobs = list(self._jobs.values())
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: (j.priority, j.created_at))
        return jobs[:limit]

    async def remove(self, job_id: str) -> bool:
        """Remove a job from the store; return True if it existed."""
        async with self._lock:
            return self._jobs.pop(job_id, None) is not None

    async def close(self) -> None:
        """No persistent resources to close."""


_REDIS_ZSET_KEY = "orchestra:queue:pending"
_REDIS_HASH_KEY = "orchestra:queue:jobs"

# Atomically pop the lowest-score member from the sorted set AND fetch its
# JSON payload from the hash in a single round-trip.  Using Lua guarantees
# both operations succeed or neither takes effect — a crash mid-way cannot
# drop the job ID before the payload is retrieved.
_DEQUEUE_LUA = """
local id = redis.call('ZPOPMIN', KEYS[1], 1)
if #id == 0 then return false end
local raw = redis.call('HGET', KEYS[2], id[1])
return raw
"""


class RedisBackend:
    """Distributed queue backed by Redis sorted set + hash."""

    def __init__(self, client: Any) -> None:
        if not _HAS_REDIS:
            raise ImportError(
                "redis not installed. Run: pip install redis"
            )
        self._client = client

    @classmethod
    async def connect(cls, dsn: str) -> "RedisBackend":
        """Create a RedisBackend connected to *dsn*."""
        if not _HAS_REDIS:
            raise ImportError(
                "redis not installed. Run: pip install redis"
            )
        client = aioredis.from_url(dsn, decode_responses=True)  # type: ignore[name-defined]
        return cls(client)

    async def enqueue(self, job: Job) -> None:
        """Add job to sorted set (score=priority) and store JSON in hash."""
        pipe = self._client.pipeline()
        pipe.zadd(_REDIS_ZSET_KEY, {job.id: job.priority})
        pipe.hset(_REDIS_HASH_KEY, job.id, json.dumps(job.to_dict()))
        await pipe.execute()

    async def dequeue(self) -> Job | None:
        """Atomically pop the highest-priority job via a Lua script.

        The Lua script runs as a single Redis command, so the pop and the hash
        lookup are indivisible — a process crash cannot leave the job ID
        removed from the sorted set while the payload is never fetched.
        """
        raw: str | None = await self._client.eval(
            _DEQUEUE_LUA, 2, _REDIS_ZSET_KEY, _REDIS_HASH_KEY
        )
        if not raw:
            return None
        return Job.from_dict(json.loads(raw))

    async def update(self, job: Job) -> None:
        """Overwrite the job JSON in the hash."""
        await self._client.hset(_REDIS_HASH_KEY, job.id, json.dumps(job.to_dict()))

    async def get(self, job_id: str) -> Job | None:
        """Return a single job by ID."""
        raw: str | None = await self._client.hget(_REDIS_HASH_KEY, job_id)
        if raw is None:
            return None
        return Job.from_dict(json.loads(raw))

    async def list_jobs(
        self, status: str | None = None, limit: int = 100
    ) -> list[Job]:
        """Return jobs from the hash, optionally filtered by status."""
        raw_map: dict[str, str] = await self._client.hgetall(_REDIS_HASH_KEY)
        jobs = [Job.from_dict(json.loads(v)) for v in raw_map.values()]
        if status is not None:
            jobs = [j for j in jobs if j.status == status]
        jobs.sort(key=lambda j: (j.priority, j.created_at))
        return jobs[:limit]

    async def remove(self, job_id: str) -> bool:
        """Remove the job from both the sorted set and the hash."""
        pipe = self._client.pipeline()
        pipe.zrem(_REDIS_ZSET_KEY, job_id)
        pipe.hdel(_REDIS_HASH_KEY, job_id)
        results: list[int] = await pipe.execute()
        return bool(results[1])

    async def close(self) -> None:
        """Close the Redis connection."""
        await self._client.aclose()


# ---------------------------------------------------------------------------
# PostgreSQL Backend
# ---------------------------------------------------------------------------

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS orchestra_jobs (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    status      TEXT NOT NULL DEFAULT 'pending',
    priority    INTEGER NOT NULL DEFAULT 5,
    max_retries INTEGER NOT NULL DEFAULT 3,
    retry_count INTEGER NOT NULL DEFAULT 0,
    created_at  DOUBLE PRECISION NOT NULL,
    started_at  DOUBLE PRECISION,
    finished_at DOUBLE PRECISION,
    result      JSONB,
    error       TEXT,
    retry_after DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS idx_orchestra_jobs_status_priority
    ON orchestra_jobs (status, priority, created_at);
"""


class PostgresBackend:
    """Durable queue backend backed by PostgreSQL.

    Uses ``SELECT ... FOR UPDATE SKIP LOCKED`` for safe concurrent dequeue
    across multiple workers without losing jobs on process crash.

    Usage::

        backend = await PostgresBackend.connect("postgresql://user:pass@localhost/db")
        worker = Worker(queue=JobQueue(backend=backend), handlers={...})
    """

    def __init__(self, pool: Any) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, dsn: str) -> "PostgresBackend":
        """Connect to PostgreSQL and ensure the jobs table exists."""
        if not _HAS_ASYNCPG:
            raise ImportError(
                "asyncpg is required for PostgresBackend. "
                "Install with: pip install asyncpg"
            )
        pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
        async with pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE)
        return cls(pool)

    async def enqueue(self, job: Job) -> None:
        """Insert a new job row (or upsert on id conflict)."""
        d = job.to_dict()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO orchestra_jobs
                    (id, name, payload, status, priority, max_retries, retry_count,
                     created_at, started_at, finished_at, result, error, retry_after)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
                ON CONFLICT (id) DO UPDATE SET
                    status = EXCLUDED.status,
                    priority = EXCLUDED.priority,
                    retry_count = EXCLUDED.retry_count,
                    retry_after = EXCLUDED.retry_after;
                """,
                d["id"], d["name"],
                json.dumps(d.get("payload") or {}),
                d["status"], d["priority"], d["max_retries"], d["retry_count"],
                d["created_at"], d.get("started_at"), d.get("finished_at"),
                json.dumps(d["result"]) if d.get("result") is not None else None,
                d.get("error"), d.get("retry_after"),
            )

    async def dequeue(self) -> Job | None:
        """Atomically claim the highest-priority pending job."""
        now = time.time()
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT *
                    FROM orchestra_jobs
                    WHERE status = 'pending'
                      AND (retry_after IS NULL OR retry_after <= $1)
                    ORDER BY priority ASC, created_at ASC
                    LIMIT 1
                    FOR UPDATE SKIP LOCKED;
                    """,
                    now,
                )
                if row is None:
                    return None
                await conn.execute(
                    "UPDATE orchestra_jobs SET status = 'running', started_at = $1 WHERE id = $2;",
                    now, row["id"],
                )
        return _row_to_job(dict(row), started_at=now)

    async def update(self, job: Job) -> None:
        """Persist updated job state."""
        d = job.to_dict()
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE orchestra_jobs SET
                    status = $2, retry_count = $3, started_at = $4,
                    finished_at = $5,
                    result = $6::jsonb,
                    error = $7, retry_after = $8
                WHERE id = $1;
                """,
                d["id"], d["status"], d["retry_count"],
                d.get("started_at"), d.get("finished_at"),
                json.dumps(d["result"]) if d.get("result") is not None else None,
                d.get("error"), d.get("retry_after"),
            )

    async def get(self, job_id: str) -> Job | None:
        """Return a single job by id."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM orchestra_jobs WHERE id = $1;", job_id
            )
        if row is None:
            return None
        return _row_to_job(dict(row))

    async def list_jobs(
        self, status: str | None = None, limit: int = 100
    ) -> list[Job]:
        """Return up to *limit* jobs, optionally filtered by status."""
        async with self._pool.acquire() as conn:
            if status is not None:
                rows = await conn.fetch(
                    "SELECT * FROM orchestra_jobs WHERE status = $1 "
                    "ORDER BY priority ASC, created_at ASC LIMIT $2;",
                    status, limit,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM orchestra_jobs "
                    "ORDER BY priority ASC, created_at ASC LIMIT $1;",
                    limit,
                )
        return [_row_to_job(dict(r)) for r in rows]

    async def remove(self, job_id: str) -> bool:
        """Delete a job row; return True if it existed."""
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM orchestra_jobs WHERE id = $1;", job_id
            )
        return result == "DELETE 1"

    async def close(self) -> None:
        """Close the asyncpg connection pool."""
        await self._pool.close()


def _row_to_job(row: dict[str, Any], **overrides: Any) -> Job:
    """Convert a database row dict to a Job dataclass."""
    result = row.get("result")
    if isinstance(result, str):
        result = json.loads(result)
    payload = row.get("payload")
    if isinstance(payload, str):
        payload = json.loads(payload)
    return Job(
        id=row["id"],
        name=row["name"],
        payload=payload or {},
        status=overrides.get("status", row["status"]),
        priority=row["priority"],
        max_retries=row["max_retries"],
        retry_count=row["retry_count"],
        created_at=row["created_at"],
        started_at=overrides.get("started_at", row.get("started_at")),
        finished_at=row.get("finished_at"),
        result=result,
        error=row.get("error"),
        retry_after=row.get("retry_after"),
    )
