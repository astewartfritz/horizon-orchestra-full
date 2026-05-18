import asyncio
import time
import uuid
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable

logger = logging.getLogger(__name__)


class MessagePriority(int, Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BULK = 4


@dataclass(order=True)
class QueuedMessage:
    priority: int = MessagePriority.NORMAL
    timestamp: float = field(default_factory=time.time)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    channel_type: str = ""
    target: str = ""
    content: str = ""
    sender_id: str = ""
    retry_count: int = 0
    max_retries: int = 3
    trace_id: str = ""

    def __post_init__(self):
        object.__setattr__(self, 'priority', self.priority if isinstance(self.priority, int) else self.priority.value)


class MessageQueue:
    def __init__(self):
        self._queues: dict[str, asyncio.PriorityQueue] = {}
        self._dlq: dict[str, list[QueuedMessage]] = {}
        self._processing: set[str] = set()
        self._running = False
        self._workers: dict[str, asyncio.Task] = {}
        self._handlers: dict[str, Callable] = {}
        self._stats: dict[str, dict] = {}

    def register_handler(self, channel_type: str, handler: Callable):
        self._handlers[channel_type] = handler
        if channel_type not in self._queues:
            self._queues[channel_type] = asyncio.PriorityQueue()
            self._dlq[channel_type] = []
            self._stats[channel_type] = {"enqueued": 0, "delivered": 0, "failed": 0, "dlq": 0}

    async def enqueue(self, message: QueuedMessage):
        channel = message.channel_type
        if channel not in self._queues:
            logger.warning(f"No handler for channel {channel}, dropping message")
            return
        sort_key = (message.priority, message.timestamp, message.id)
        await self._queues[channel].put((sort_key, message))
        self._stats[channel]["enqueued"] += 1

    async def enqueue_many(self, messages: list[QueuedMessage]):
        for msg in messages:
            await self.enqueue(msg)

    def start_worker(self, channel_type: str, num_workers: int = 1):
        if channel_type not in self._handlers:
            raise ValueError(f"No handler registered for channel {channel_type}")
        self._running = True
        for i in range(num_workers):
            worker_id = f"{channel_type}-worker-{i}"
            task = asyncio.create_task(self._worker_loop(channel_type, worker_id))
            self._workers[worker_id] = task

    def start_all(self, workers_per_channel: int = 1):
        for channel_type in self._handlers:
            self.start_worker(channel_type, workers_per_channel)

    async def stop_all(self):
        self._running = False
        for worker_id, task in self._workers.items():
            task.cancel()
        await asyncio.gather(*self._workers.values(), return_exceptions=True)
        self._workers.clear()

    async def _worker_loop(self, channel_type: str, worker_id: str):
        queue = self._queues[channel_type]
        handler = self._handlers[channel_type]
        while self._running:
            try:
                _, message = await asyncio.wait_for(queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            self._processing.add(message.id)
            try:
                result = handler(message)
                if asyncio.iscoroutine(result):
                    await result
                self._stats[channel_type]["delivered"] += 1
            except Exception as e:
                logger.error(f"Worker {worker_id} failed to deliver message {message.id}: {e}")
                message.retry_count += 1
                if message.retry_count <= message.max_retries:
                    sort_key = (message.priority + message.retry_count, time.time() + message.retry_count, message.id)
                    await queue.put((sort_key, message))
                else:
                    self._dlq[channel_type].append(message)
                    self._stats[channel_type]["dlq"] += 1
                self._stats[channel_type]["failed"] += 1
            finally:
                self._processing.discard(message.id)
                queue.task_done()

    def get_stats(self, channel_type: str | None = None) -> dict:
        if channel_type:
            return dict(self._stats.get(channel_type, {}))
        return {k: dict(v) for k, v in self._stats.items()}

    def get_dlq(self, channel_type: str) -> list[QueuedMessage]:
        return list(self._dlq.get(channel_type, []))

    def requeue_dlq(self, channel_type: str):
        dlq = self._dlq.get(channel_type, [])
        self._dlq[channel_type] = []
        for msg in dlq:
            msg.retry_count = 0
            asyncio.create_task(self.enqueue(msg))

    def queue_depth(self, channel_type: str) -> int:
        q = self._queues.get(channel_type)
        return q.qsize() if q else 0
