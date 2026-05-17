import pytest

"""Tests for the asyncio-safe TTL LRU cache implementation.

This module contains pytest async tests verifying the behavior of the
:class:`orchestra.utils.lru_cache.TTLCache` class, including basic storage,
LRU eviction under capacity constraints, TTL expiration, concurrency safety,
and the clear operation.
"""

import asyncio

from orchestra.utils.lru_cache import TTLCache

pytestmark = pytest.mark.asyncio


async def test_basic_put_get() -> None:
    """Verify that a stored key can be retrieved."""
    cache = TTLCache(max_size=10, ttl_seconds=None)
    await cache.set("foo", "bar")
    assert await cache.get("foo") == "bar"


async def test_get_missing_key_returns_none() -> None:
    """Verify that a missing key returns None."""
    cache = TTLCache(max_size=10, ttl_seconds=None)
    assert await cache.get("missing") is None


async def test_capacity_eviction_lru() -> None:
    """Verify that the least recently used item is evicted when max_size is exceeded."""
    cache = TTLCache(max_size=2, ttl_seconds=None)
    await cache.set("a", 1)
    await cache.set("b", 2)
    # Access "a" to make it recently used.
    assert await cache.get("a") == 1
    await cache.set("c", 3)
    assert await cache.get("a") == 1
    assert await cache.get("b") is None
    assert await cache.get("c") == 3


async def test_ttl_expiry() -> None:
    """Verify that entries expire after the configured TTL."""
    cache = TTLCache(max_size=10, ttl_seconds=0.1)
    await cache.set("key", "value")
    assert await cache.get("key") == "value"
    await asyncio.sleep(0.15)
    assert await cache.get("key") is None


async def test_concurrent_gather() -> None:
    """Verify thread-safe behavior under concurrent asyncio operations."""
    cache = TTLCache(max_size=200, ttl_seconds=None)

    async def setter(i: int) -> None:
        await cache.set(str(i), i)

    async def getter(i: int) -> int | None:
        return await cache.get(str(i))

    # Concurrent writes
    await asyncio.gather(*(setter(i) for i in range(100)))
    # Concurrent reads
    results = await asyncio.gather(*(getter(i) for i in range(100)))
    assert results == list(range(100))

    # Concurrent mixed workload
    async def mixed(i: int) -> None:
        await cache.set(f"mixed_{i}", i)
        assert await cache.get(f"mixed_{i}") == i
        if i % 2 == 0:
            await cache.delete(f"mixed_{i}")

    await asyncio.gather(*(mixed(i) for i in range(100)))
    for i in range(100):
        if i % 2 == 0:
            assert await cache.get(f"mixed_{i}") is None
        else:
            assert await cache.get(f"mixed_{i}") == i


async def test_clear() -> None:
    """Verify that clear removes all entries."""
    cache = TTLCache(max_size=10, ttl_seconds=None)
    for i in range(5):
        await cache.set(str(i), i)
    await cache.clear()
    for i in range(5):
        assert await cache.get(str(i)) is None


async def test_delete() -> None:
    """Verify that delete removes a specific entry."""
    cache = TTLCache(max_size=10, ttl_seconds=None)
    await cache.set("to_delete", 42)
    await cache.delete("to_delete")
    assert await cache.get("to_delete") is None