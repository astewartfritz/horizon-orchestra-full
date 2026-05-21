from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class QueuePriority(int, Enum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3
    BACKGROUND = 4


@dataclass
class QueueTask:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_input: str = ""
    intent: str = "general"
    priority: QueuePriority = QueuePriority.MEDIUM
    lanes: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    enqueued_at: float = 0.0
    picked_at: float = 0.0
    completed_at: float = 0.0
    status: str = "pending"
    result: str | None = None
    error: str | None = None
    retries: int = 0
    max_retries: int = 3
    ttl_seconds: int = 3600
    rate_limit_key: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class DistributedTaskQueue:
    """Redis-backed priority task queue with backpressure and rate limiting.

    Architecture:
      Producer → LPUSH to priority list → Worker BLPOP → Process → ACK
      Dead-letter queue for failed tasks after max_retries.
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        queue_prefix: str = "orchestra:queue:",
        dlq_prefix: str = "orchestra:dlq:",
        max_queue_depth: int = 100_000,
        rate_limit_per_second: int = 0,
        backpressure_threshold: int = 10_000,
    ):
        self.redis_url = redis_url
        self.queue_prefix = queue_prefix
        self.dlq_prefix = dlq_prefix
        self.max_depth = max_queue_depth
        self.rate_limit_per_second = rate_limit_per_second
        self.backpressure_threshold = backpressure_threshold
        self._redis = None
        self._connected = False
        self._rate_buckets: dict[str, list[float]] = {}

    async def _connect(self):
        if self._redis is None:
            try:
                import redis.asyncio as aioredis
                self._redis = aioredis.from_url(
                    self.redis_url, decode_responses=True,
                    socket_connect_timeout=2, socket_timeout=5,
                )
                await self._redis.ping()
                self._connected = True
            except Exception:
                self._connected = False

    def _queue_key(self, priority: QueuePriority) -> str:
        return f"{self.queue_prefix}p{priority.value}"

    def _dlq_key(self) -> str:
        return f"{self.dlq_prefix}tasks"

    def _processing_key(self) -> str:
        return f"{self.queue_prefix}processing"

    def _task_key(self, task_id: str) -> str:
        return f"{self.queue_prefix}task:{task_id}"

    def _serialize(self, task: QueueTask) -> str:
        return json.dumps({
            "task_id": task.task_id,
            "user_input": task.user_input,
            "intent": task.intent,
            "priority": task.priority.value,
            "lanes": task.lanes,
            "created_at": task.created_at,
            "enqueued_at": task.enqueued_at or time.time(),
            "picked_at": task.picked_at,
            "completed_at": task.completed_at,
            "status": task.status,
            "result": task.result,
            "error": task.error,
            "retries": task.retries,
            "max_retries": task.max_retries,
            "ttl_seconds": task.ttl_seconds,
            "rate_limit_key": task.rate_limit_key,
            "metadata": task.metadata,
        }, default=str)

    def _deserialize(self, raw: str) -> QueueTask | None:
        try:
            d = json.loads(raw)
            return QueueTask(
                task_id=d.get("task_id", uuid.uuid4().hex[:12]),
                user_input=d.get("user_input", ""),
                intent=d.get("intent", "general"),
                priority=QueuePriority(d.get("priority", 2)),
                lanes=d.get("lanes", []),
                created_at=d.get("created_at", 0.0),
                enqueued_at=d.get("enqueued_at", 0.0),
                picked_at=d.get("picked_at", 0.0),
                completed_at=d.get("completed_at", 0.0),
                status=d.get("status", "pending"),
                result=d.get("result"),
                error=d.get("error"),
                retries=d.get("retries", 0),
                max_retries=d.get("max_retries", 3),
                ttl_seconds=d.get("ttl_seconds", 3600),
                rate_limit_key=d.get("rate_limit_key", ""),
                metadata=d.get("metadata", {}),
            )
        except (json.JSONDecodeError, KeyError, ValueError):
            return None

    # ── Producer API ──

    async def enqueue(self, task: QueueTask) -> bool:
        if not self._connected:
            await self._connect()
        if not self._connected:
            return False

        depth = await self._redis.llen(self._queue_key(task.priority))
        if depth >= self.max_depth:
            return False

        if self.rate_limit_per_second > 0 and task.rate_limit_key:
            if not self._check_rate_limit(task.rate_limit_key):
                return False

        if self.backpressure_threshold > 0 and depth >= self.backpressure_threshold:
            task.metadata["backpressure_delayed"] = True

        task.enqueued_at = time.time()
        raw = self._serialize(task)
        await self._redis.setex(self._task_key(task.task_id), task.ttl_seconds, raw)
        await self._redis.lpush(self._queue_key(task.priority), task.task_id)
        return True

    # ── Consumer API ──

    async def dequeue(self, timeout: int = 5) -> QueueTask | None:
        if not self._connected:
            await self._connect()
        if not self._connected:
            return None

        keys = [self._queue_key(p) for p in sorted(QueuePriority, key=lambda x: x.value)]
        result = await self._redis.blpop(keys, timeout=timeout)
        if not result:
            return None

        _, task_id = result
        raw = await self._redis.get(self._task_key(task_id))
        if not raw:
            return None

        task = self._deserialize(raw)
        if not task:
            return None

        task.picked_at = time.time()
        task.status = "running"
        processing_key = self._processing_key()
        await self._redis.sadd(processing_key, task.task_id)
        await self._redis.expire(processing_key, task.ttl_seconds)
        return task

    async def ack(self, task_id: str, success: bool = True, result: str | None = None, error: str | None = None) -> bool:
        if not self._connected:
            return False

        raw = await self._redis.get(self._task_key(task_id))
        if not raw:
            return False

        task = self._deserialize(raw)
        if not task:
            return False

        task.completed_at = time.time()
        task.status = "completed" if success else "failed"
        task.result = result
        task.error = error

        await self._redis.setex(self._task_key(task_id), task.ttl_seconds, self._serialize(task))
        await self._redis.srem(self._processing_key(), task_id)

        if not success and task.retries < task.max_retries:
            task.retries += 1
            task.status = "pending"
            await self._redis.setex(self._task_key(task_id), task.ttl_seconds, self._serialize(task))
            await self._redis.lpush(self._queue_key(task.priority), task_id)
        elif not success:
            await self._redis.lpush(self._dlq_key(), task_id)
        return True

    async def nack(self, task_id: str, requeue: bool = True) -> bool:
        if not self._connected:
            return False

        await self._redis.srem(self._processing_key(), task_id)
        if requeue:
            raw = await self._redis.get(self._task_key(task_id))
            if raw:
                task = self._deserialize(raw)
                if task:
                    await self._redis.lpush(self._queue_key(task.priority), task_id)
        return True

    # ── Monitoring ──

    async def depth(self, priority: QueuePriority | None = None) -> dict[str, int]:
        if not self._connected:
            await self._connect()
        if not self._connected:
            return {}

        result = {}
        priorities = [priority] if priority else list(QueuePriority)
        for p in priorities:
            try:
                result[p.name] = await self._redis.llen(self._queue_key(p))
            except Exception:
                result[p.name] = -1
        return result

    async def processing_count(self) -> int:
        if not self._connected:
            return 0
        try:
            return await self._redis.scard(self._processing_key())
        except Exception:
            return 0

    async def dlq_count(self) -> int:
        if not self._connected:
            return 0
        try:
            return await self._redis.llen(self._dlq_key())
        except Exception:
            return 0

    async def is_backpressured(self) -> bool:
        if self.backpressure_threshold <= 0:
            return False
        depths = await self.depth()
        total = sum(depths.values())
        return total >= self.backpressure_threshold

    # ── Rate limiting ──

    def _check_rate_limit(self, key: str) -> bool:
        now = time.time()
        bucket = self._rate_buckets.setdefault(key, [])
        cutoff = now - 1.0
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= self.rate_limit_per_second:
            return False
        bucket.append(now)
        return True
