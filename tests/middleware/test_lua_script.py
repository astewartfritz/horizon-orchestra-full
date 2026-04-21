"""Tests for the Lua token-bucket script.

Tries fakeredis first, then real Redis at localhost:6379.
Skips gracefully if neither is available.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from orchestra.middleware._lua import TOKEN_BUCKET_SCRIPT, eval_token_bucket

def _make_client():
    """Get a Redis client — prefer fakeredis[lua], fall back to real Redis."""
    try:
        import fakeredis.aioredis as _fake
        return _fake.FakeRedis(decode_responses=False), None
    except ImportError:
        pass
    try:
        import redis.asyncio as _real_redis
        return _real_redis.from_url("redis://localhost:6379", decode_responses=False), None
    except ImportError:
        return None, "Neither fakeredis[lua] nor redis.asyncio available"


_redis_client, _skip_reason = _make_client()


@unittest.skipIf(_skip_reason is not None, _skip_reason)
class TestLuaScript(unittest.IsolatedAsyncioTestCase):
    """Test Lua token-bucket script against fakeredis or real Redis."""

    async def asyncSetUp(self):
        self.redis = _redis_client
        if self.redis is None:
            self.skipTest("No Redis backend available")
        try:
            await self.redis.ping()
        except Exception:
            self.skipTest("Redis not reachable")
        # Clean up test keys
        keys = await self.redis.keys("test:rl:*")
        if keys:
            await self.redis.delete(*keys)

    async def test_first_request_allowed(self):
        allowed, remaining, retry = await eval_token_bucket(
            self.redis,
            key="test:rl:first",
            now_ms=1000,
            capacity=10,
            refill_per_ms=0.01,
            cost=1,
            ttl_ms=60000,
        )
        self.assertTrue(allowed)
        self.assertAlmostEqual(remaining, 9.0, delta=0.1)
        self.assertEqual(retry, 0)

    async def test_exhaust_tokens(self):
        for i in range(10):
            allowed, remaining, _ = await eval_token_bucket(
                self.redis,
                key="test:rl:exhaust",
                now_ms=1000,
                capacity=10,
                refill_per_ms=0.01,
                cost=1,
                ttl_ms=60000,
            )
        # Should have used all 10 tokens
        allowed, remaining, retry = await eval_token_bucket(
            self.redis,
            key="test:rl:exhaust",
            now_ms=1000,
            capacity=10,
            refill_per_ms=0.01,
            cost=1,
            ttl_ms=60000,
        )
        self.assertFalse(allowed)
        self.assertGreater(retry, 0)

    async def test_refill_over_time(self):
        # Use all tokens at t=1000
        for _ in range(5):
            await eval_token_bucket(
                self.redis,
                key="test:rl:refill",
                now_ms=1000,
                capacity=5,
                refill_per_ms=0.01,
                cost=1,
                ttl_ms=60000,
            )
        # At t=2000 (1000ms later at 0.01/ms = 10 tokens refilled, capped at 5)
        allowed, remaining, _ = await eval_token_bucket(
            self.redis,
            key="test:rl:refill",
            now_ms=2000,
            capacity=5,
            refill_per_ms=0.01,
            cost=1,
            ttl_ms=60000,
        )
        self.assertTrue(allowed)
        self.assertGreater(remaining, 0)

    async def test_cost_parameter(self):
        allowed, remaining, _ = await eval_token_bucket(
            self.redis,
            key="test:rl:cost",
            now_ms=1000,
            capacity=10,
            refill_per_ms=0.001,
            cost=8,
            ttl_ms=60000,
        )
        self.assertTrue(allowed)
        self.assertAlmostEqual(remaining, 2.0, delta=0.1)

        # Cost 3 should fail (only 2 remaining)
        allowed, _, retry = await eval_token_bucket(
            self.redis,
            key="test:rl:cost",
            now_ms=1000,
            capacity=10,
            refill_per_ms=0.001,
            cost=3,
            ttl_ms=60000,
        )
        self.assertFalse(allowed)

    async def test_retry_after_math(self):
        # Exhaust bucket
        for _ in range(10):
            await eval_token_bucket(
                self.redis,
                key="test:rl:retry",
                now_ms=1000,
                capacity=10,
                refill_per_ms=0.01,
                cost=1,
                ttl_ms=60000,
            )
        # 1 token deficit at 0.01/ms → retry_after ~= 100ms
        _, _, retry = await eval_token_bucket(
            self.redis,
            key="test:rl:retry",
            now_ms=1000,
            capacity=10,
            refill_per_ms=0.01,
            cost=1,
            ttl_ms=60000,
        )
        self.assertGreater(retry, 0)
        self.assertLessEqual(retry, 200)


class TestEvalShaFallback(unittest.IsolatedAsyncioTestCase):
    """Test the EVALSHA → EVAL fallback logic with mocks."""

    async def test_noscript_triggers_eval_fallback(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(side_effect=Exception("NOSCRIPT No matching script"))
        redis.eval = AsyncMock(return_value=[1, 9, 0])

        allowed, remaining, retry = await eval_token_bucket(
            redis,
            key="test:key",
            now_ms=1000,
            capacity=10,
            refill_per_ms=0.01,
            cost=1,
            ttl_ms=60000,
        )
        self.assertTrue(allowed)
        redis.eval.assert_called_once()

    async def test_non_noscript_error_propagates(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(side_effect=ConnectionError("Connection refused"))

        with self.assertRaises(ConnectionError):
            await eval_token_bucket(
                redis,
                key="test:key",
                now_ms=1000,
                capacity=10,
                refill_per_ms=0.01,
                cost=1,
                ttl_ms=60000,
            )


if __name__ == "__main__":
    unittest.main()
