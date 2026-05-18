import time
import asyncio
import logging
from enum import Enum
from typing import Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class ChannelHealthStatus(str, Enum):
    UNKNOWN = "unknown"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"
    RATE_LIMITED = "rate_limited"
    DEGRADED = "degraded"


@dataclass
class ChannelHealth:
    channel_type: str = ""
    status: ChannelHealthStatus = ChannelHealthStatus.UNKNOWN
    last_ok: float = 0.0
    last_error: float = 0.0
    consecutive_failures: int = 0
    total_messages_sent: int = 0
    total_messages_received: int = 0
    total_errors: int = 0
    avg_latency_ms: float = 0.0
    last_error_message: str = ""


class ChannelHealthMonitor:
    def __init__(self, check_interval: float = 30.0):
        self._channels: dict[str, ChannelHealth] = {}
        self._check_interval = check_interval
        self._running = False
        self._checkers: dict[str, callable] = {}
        self._task: asyncio.Task | None = None

    def register_channel(self, channel_type: str, checker: Callable | None = None):
        if channel_type not in self._channels:
            self._channels[channel_type] = ChannelHealth(channel_type=channel_type)
        if checker:
            self._checkers[channel_type] = checker

    def record_success(self, channel_type: str, latency_ms: float = 0.0):
        h = self._channels.setdefault(channel_type, ChannelHealth(channel_type=channel_type))
        h.status = ChannelHealthStatus.CONNECTED
        h.last_ok = time.time()
        h.consecutive_failures = 0
        h.total_messages_sent += 1
        h.avg_latency_ms = (h.avg_latency_ms * (h.total_messages_sent - 1) + latency_ms) / h.total_messages_sent if h.total_messages_sent > 0 else latency_ms

    def record_receive(self, channel_type: str):
        h = self._channels.setdefault(channel_type, ChannelHealth(channel_type=channel_type))
        h.total_messages_received += 1

    def record_error(self, channel_type: str, error: str = ""):
        h = self._channels.setdefault(channel_type, ChannelHealth(channel_type=channel_type))
        h.status = ChannelHealthStatus.ERROR
        h.last_error = time.time()
        h.consecutive_failures += 1
        h.total_errors += 1
        h.last_error_message = error

    def get_status(self, channel_type: str) -> ChannelHealth | None:
        return self._channels.get(channel_type)

    def all_status(self) -> dict[str, ChannelHealth]:
        return dict(self._channels)

    def is_healthy(self, channel_type: str) -> bool:
        h = self._channels.get(channel_type)
        if not h:
            return False
        return h.status == ChannelHealthStatus.CONNECTED and h.consecutive_failures < 5

    def start(self):
        self._running = True
        self._task = asyncio.create_task(self._check_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _check_loop(self):
        while self._running:
            for channel_type, checker in self._checkers.items():
                try:
                    if asyncio.iscoroutinefunction(checker):
                        ok = await checker()
                    else:
                        ok = checker()
                    h = self._channels.get(channel_type)
                    if h:
                        h.status = ChannelHealthStatus.CONNECTED if ok else ChannelHealthStatus.DISCONNECTED
                except Exception as e:
                    self.record_error(channel_type, str(e))
            await asyncio.sleep(self._check_interval)
