"""Asyncio-safe in-memory token bucket — fallback limiter when Redis is unavailable."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field


@dataclass
class _BucketState:
    tokens: float
    last_refill: float  # monotonic seconds


class LocalTokenBucket:
    """Per-tenant in-memory token bucket.

    Thread-safety is achieved via an asyncio Lock (one lock per bucket).
    This limiter is *fail-open*: if anything unexpected happens, the request
    is allowed through.
    """

    def __init__(self, capacity: int, refill_per_second: float) -> None:
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self._buckets: dict[str, _BucketState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, tenant_id: str) -> asyncio.Lock:
        if tenant_id not in self._locks:
            self._locks[tenant_id] = asyncio.Lock()
        return self._locks[tenant_id]

    async def consume(
        self, tenant_id: str, cost: int = 1
    ) -> tuple[bool, float, int]:
        """Try to consume *cost* tokens for *tenant_id*.

        Returns (allowed, remaining_tokens, retry_after_ms).
        """
        lock = self._get_lock(tenant_id)
        async with lock:
            now = time.monotonic()
            bucket = self._buckets.get(tenant_id)
            if bucket is None:
                bucket = _BucketState(tokens=float(self.capacity), last_refill=now)
                self._buckets[tenant_id] = bucket

            # Refill
            elapsed = max(0.0, now - bucket.last_refill)
            bucket.tokens = min(
                float(self.capacity),
                bucket.tokens + elapsed * self.refill_per_second,
            )
            bucket.last_refill = now

            if bucket.tokens >= cost:
                bucket.tokens -= cost
                return True, bucket.tokens, 0
            else:
                deficit = cost - bucket.tokens
                if self.refill_per_second > 0:
                    retry_after_ms = int(
                        (deficit / self.refill_per_second) * 1000
                    ) + 1
                else:
                    retry_after_ms = -1  # infinite wait — no refill
                return False, bucket.tokens, retry_after_ms

    def reset(self, tenant_id: str | None = None) -> None:
        """Reset bucket(s). If *tenant_id* is None, reset all."""
        if tenant_id is None:
            self._buckets.clear()
            self._locks.clear()
        else:
            self._buckets.pop(tenant_id, None)
            self._locks.pop(tenant_id, None)
