"""Asyncio-safe LRU cache with optional TTL."""

import asyncio
from collections import OrderedDict
from collections.abc import Hashable
from time import monotonic
from typing import Any


class TTLCache:
    """An asyncio-safe LRU cache with optional time-to-live expiration.

    Entries are evicted based on least-recently-used (LRU) order when the
    cache exceeds ``max_size``, and optionally expired after ``ttl_seconds``.
    Expired items are purged opportunistically during read and write
    operations so no background task is required.

    Attributes:
        max_size: Maximum number of entries to retain.
        ttl_seconds: Optional time-to-live in seconds. ``None`` disables TTL.
    """

    def __init__(self, max_size: int, ttl_seconds: float | None = None) -> None:
        """Initialize the cache.

        Args:
            max_size: Maximum number of entries before LRU eviction.
            ttl_seconds: Optional TTL in seconds. ``None`` disables expiration.

        Raises:
            ValueError: If ``max_size`` is not a positive integer.
        """
        if max_size <= 0:
            raise ValueError("max_size must be a positive integer")
        self._max_size = max_size
        self._ttl_seconds = ttl_seconds
        self._cache: OrderedDict[Hashable, tuple[float | None, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    def _purge_expired(self) -> None:
        """Remove all entries whose TTL has passed."""
        now = monotonic()
        expired = [
            key
            for key, (expires_at, _) in self._cache.items()
            if expires_at is not None and now >= expires_at
        ]
        for key in expired:
            del self._cache[key]

    async def get(self, key: Hashable) -> Any | None:
        """Retrieve a value by key.

        Args:
            key: The cache key.

        Returns:
            The cached value, or ``None`` if the key is missing or expired.
        """
        async with self._lock:
            self._purge_expired()
            if key not in self._cache:
                return None
            self._cache.move_to_end(key)
            return self._cache[key][1]

    async def set(self, key: Hashable, value: Any) -> None:
        """Store a value under key.

        If the cache exceeds ``max_size``, the oldest entry is evicted.
        Expired entries are removed before insertion.

        Args:
            key: The cache key.
            value: The value to cache.
        """
        async with self._lock:
            self._purge_expired()
            expires_at: float | None = None
            if self._ttl_seconds is not None:
                expires_at = monotonic() + self._ttl_seconds
            self._cache[key] = (expires_at, value)
            self._cache.move_to_end(key)
            while len(self._cache) > self._max_size:
                self._cache.popitem(last=False)

    async def delete(self, key: Hashable) -> None:
        """Remove a specific key from the cache.

        Args:
            key: The cache key.
        """
        async with self._lock:
            if key in self._cache:
                del self._cache[key]

    async def clear(self) -> None:
        """Remove all entries from the cache."""
        async with self._lock:
            self._cache.clear()