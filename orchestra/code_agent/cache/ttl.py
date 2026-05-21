"""Simple in-process TTL cache.

Thread-safe, no external dependencies. Suitable for caching market prices,
news, search results, and any other short-lived data.

Usage::

    from orchestra.code_agent.cache.ttl import TTLCache

    cache = TTLCache(ttl=60)  # 60s TTL
    cache.set("AAPL", {"price": 201.5})
    val = cache.get("AAPL")   # None if expired
"""
from __future__ import annotations

import threading
import time
from typing import Any


class TTLCache:
    def __init__(self, ttl: float = 60.0, maxsize: int = 1_000) -> None:
        self._ttl = ttl
        self._maxsize = maxsize
        self._store: dict[str, tuple[Any, float]] = {}  # key -> (value, expires_at)
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        expires_at = time.monotonic() + (ttl if ttl is not None else self._ttl)
        with self._lock:
            if len(self._store) >= self._maxsize:
                self._evict()
            self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def _evict(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        if len(self._store) >= self._maxsize:
            oldest = min(self._store, key=lambda k: self._store[k][1])
            del self._store[oldest]

    def stats(self) -> dict[str, int]:
        now = time.monotonic()
        with self._lock:
            total = len(self._store)
            live = sum(1 for _, (_, exp) in self._store.items() if now <= exp)
        return {"total": total, "live": live, "expired": total - live}

    def __len__(self) -> int:
        return len(self._store)


# ---------------------------------------------------------------------------
# Module-level shared caches (imported by price/news fetchers)
# ---------------------------------------------------------------------------

# 60-second TTL for live price data
price_cache = TTLCache(ttl=60, maxsize=500)

# 5-minute TTL for news headlines
news_cache = TTLCache(ttl=300, maxsize=200)

# 10-minute TTL for search results / web fetch
search_cache = TTLCache(ttl=600, maxsize=100)
