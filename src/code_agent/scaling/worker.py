from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from code_agent.scaling.task_queue import DistributedTaskQueue, QueuePriority, QueueTask

logger = logging.getLogger(__name__)


@dataclass
class Worker:
    worker_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    host: str = "localhost"
    port: int = 0
    lanes: list[str] = field(default_factory=lambda: ["general"])
    status: str = "idle"
    task_count: int = 0
    error_count: int = 0
    started_at: float = field(default_factory=time.time)
    last_heartbeat: float = field(default_factory=time.time)
    max_concurrency: int = 1
    current_tasks: set[str] = field(default_factory=set)


class WorkerPool:
    """Stateless worker pool that pulls tasks from DistributedTaskQueue.

    Each worker is an async coroutine that:
      1. Registers itself in Redis (heartbeat + metadata)
      2. BLPOPs from the queue
      3. Processes via the provided handler
      4. ACKs/NACKs the task
      5. Reports metrics
    """

    def __init__(
        self,
        task_queue: DistributedTaskQueue,
        handler: Callable[[QueueTask], Any],
        redis_url: str = "redis://localhost:6379/0",
        worker_prefix: str = "orchestra:worker:",
        pool_size: int = 4,
        poll_interval: float = 1.0,
        heartbeat_interval: float = 10.0,
        max_tasks_per_worker: int = 100,
    ):
        self.task_queue = task_queue
        self.handler = handler
        self.redis_url = redis_url
        self.worker_prefix = worker_prefix
        self.pool_size = pool_size
        self.poll_interval = poll_interval
        self.heartbeat_interval = heartbeat_interval
        self.max_tasks_per_worker = max_tasks_per_worker
        self.workers: list[Worker] = []
        self._redis = None
        self._connected = False
        self._running = False
        self._tasks: set[asyncio.Task] = set()

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
                logger.warning("WorkerPool: Redis unavailable, using local only")

    def _worker_key(self, worker_id: str) -> str:
        return f"{self.worker_prefix}{worker_id}"

    def _workers_set_key(self) -> str:
        return f"{self.worker_prefix}active"

    def _serialize_worker(self, w: Worker) -> dict:
        return {
            "worker_id": w.worker_id,
            "host": w.host,
            "port": w.port,
            "lanes": w.lanes,
            "status": w.status,
            "task_count": w.task_count,
            "error_count": w.error_count,
            "started_at": w.started_at,
            "last_heartbeat": w.last_heartbeat,
            "max_concurrency": w.max_concurrency,
            "current_tasks": list(w.current_tasks),
        }

    async def _register_worker(self, w: Worker):
        if not self._connected:
            return
        import json
        raw = json.dumps(self._serialize_worker(w), default=str)
        await self._redis.setex(self._worker_key(w.worker_id), 30, raw)
        await self._redis.sadd(self._workers_set_key(), w.worker_id)

    async def _heartbeat(self, w: Worker):
        while self._running:
            w.last_heartbeat = time.time()
            await self._register_worker(w)
            await asyncio.sleep(self.heartbeat_interval)

    async def _process_loop(self, w: Worker):
        await self._register_worker(w)
        heartbeat_task = asyncio.create_task(self._heartbeat(w))
        self._tasks.add(heartbeat_task)

        try:
            while self._running and w.task_count < self.max_tasks_per_worker:
                task = await self.task_queue.dequeue(timeout=int(self.poll_interval))
                if not task:
                    continue

                w.current_tasks.add(task.task_id)
                w.status = "busy"
                try:
                    result = await self.handler(task)
                    if isinstance(result, tuple):
                        success, output = result[0], result[1] if len(result) > 1 else None
                        error = result[2] if len(result) > 2 else None
                    else:
                        success, output, error = True, str(result), None

                    await self.task_queue.ack(task.task_id, success=success, result=output, error=error)
                    w.task_count += 1
                    if not success:
                        w.error_count += 1
                except Exception as e:
                    await self.task_queue.ack(task.task_id, success=False, error=str(e))
                    w.error_count += 1
                finally:
                    w.current_tasks.discard(task.task_id)
                    w.status = "idle" if len(w.current_tasks) == 0 else "busy"
        except asyncio.CancelledError:
            pass
        finally:
            heartbeat_task.cancel()
            w.status = "stopped"

    async def start(self):
        self._running = True
        await self._connect()
        self.workers = []
        self._tasks = set()

        for i in range(self.pool_size):
            w = Worker(
                worker_id=f"worker-{i}-{uuid.uuid4().hex[:4]}",
            )
            self.workers.append(w)
            task = asyncio.create_task(self._process_loop(w))
            self._tasks.add(task)
            logger.info(f"Worker {w.worker_id} started")

    async def stop(self, timeout: float = 10.0):
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.wait(self._tasks, timeout=timeout)
        self._tasks.clear()
        self.workers.clear()

    async def scale(self, target_size: int):
        current = len(self.workers)
        if target_size > current:
            for i in range(current, target_size):
                w = Worker(
                    worker_id=f"worker-{i}-{uuid.uuid4().hex[:4]}",
                )
                self.workers.append(w)
                task = asyncio.create_task(self._process_loop(w))
                self._tasks.add(task)
        elif target_size < current:
            for w in self.workers[target_size:]:
                w.status = "draining"
            self.workers = self.workers[:target_size]

    async def list_workers(self) -> list[dict]:
        if not self._connected:
            return [self._serialize_worker(w) for w in self.workers]
        import json
        worker_ids = await self._redis.smembers(self._workers_set_key())
        result = []
        for wid in worker_ids:
            raw = await self._redis.get(self._worker_key(wid))
            if raw:
                try:
                    result.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
        return result

    @property
    def total_task_count(self) -> int:
        return sum(w.task_count for w in self.workers)

    @property
    def total_error_count(self) -> int:
        return sum(w.error_count for w in self.workers)
