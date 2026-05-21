import asyncio
import time
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable
from enum import Enum

logger = logging.getLogger(__name__)


class RetryStrategy(str, Enum):
    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    LINEAR = "linear"
    JITTER = "jitter"


@dataclass
class RetryConfig:
    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    retryable_exceptions: tuple = (Exception,)


class ChannelRetryEngine:
    def __init__(self):
        self._configs: dict[str, RetryConfig] = {}

    def set_config(self, channel_type: str, config: RetryConfig):
        self._configs[channel_type] = config

    def get_config(self, channel_type: str) -> RetryConfig:
        return self._configs.get(channel_type, RetryConfig())

    def _calculate_delay(self, attempt: int, config: RetryConfig) -> float:
        if config.strategy == RetryStrategy.FIXED:
            delay = config.base_delay
        elif config.strategy == RetryStrategy.LINEAR:
            delay = config.base_delay * (attempt + 1)
        elif config.strategy == RetryStrategy.JITTER:
            import random
            delay = config.base_delay * (2 ** attempt)
            delay = delay * (0.5 + random.random() * 0.5)
        else:
            delay = config.base_delay * (2 ** attempt)
        return min(delay, config.max_delay)

    async def execute(self, channel_type: str, fn: Callable[[], Awaitable],
                      config: RetryConfig | None = None) -> tuple[bool, str]:
        cfg = config or self.get_config(channel_type)
        last_error = ""
        for attempt in range(cfg.max_retries + 1):
            try:
                result = fn()
                if asyncio.iscoroutine(result):
                    await result
                return True, ""
            except cfg.retryable_exceptions as e:
                last_error = str(e)
                if attempt < cfg.max_retries:
                    delay = self._calculate_delay(attempt, cfg)
                    logger.warning(f"Retry[{channel_type}] attempt {attempt + 1}/{cfg.max_retries} "
                                  f"failed: {e}, retrying in {delay:.1f}s")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"Retry[{channel_type}] all {cfg.max_retries} retries exhausted: {e}")
        return False, last_error
