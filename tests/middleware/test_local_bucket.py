"""Tests for the in-memory token bucket fallback limiter."""

from __future__ import annotations

import asyncio
import unittest

from orchestra.middleware._bucket import LocalTokenBucket


class TestLocalTokenBucket(unittest.IsolatedAsyncioTestCase):
    """Refill math, capacity limits, and concurrent access."""

    async def test_initial_bucket_is_full(self):
        bucket = LocalTokenBucket(capacity=10, refill_per_second=1.0)
        allowed, remaining, retry_after = await bucket.consume("t1", cost=1)
        self.assertTrue(allowed)
        self.assertAlmostEqual(remaining, 9.0, delta=0.5)
        self.assertEqual(retry_after, 0)

    async def test_exhaust_bucket(self):
        bucket = LocalTokenBucket(capacity=3, refill_per_second=0.0)
        for _ in range(3):
            allowed, _, _ = await bucket.consume("t1")
            self.assertTrue(allowed)
        # 4th request should fail
        allowed, remaining, retry_after = await bucket.consume("t1")
        self.assertFalse(allowed)
        self.assertNotEqual(retry_after, 0)

    async def test_refill_over_time(self):
        bucket = LocalTokenBucket(capacity=5, refill_per_second=100.0)
        # Drain all
        for _ in range(5):
            await bucket.consume("t1")
        # Wait a bit for refill
        await asyncio.sleep(0.06)
        allowed, remaining, _ = await bucket.consume("t1")
        self.assertTrue(allowed)
        self.assertGreater(remaining, 0)

    async def test_capacity_cap(self):
        """Tokens never exceed capacity even after long refill periods."""
        bucket = LocalTokenBucket(capacity=10, refill_per_second=1000.0)
        await asyncio.sleep(0.05)
        allowed, remaining, _ = await bucket.consume("t1", cost=1)
        self.assertTrue(allowed)
        # remaining should not exceed capacity - cost
        self.assertLessEqual(remaining, 10.0)

    async def test_tenant_isolation(self):
        bucket = LocalTokenBucket(capacity=2, refill_per_second=0.001)
        await bucket.consume("t1")
        await bucket.consume("t1")
        # t1 exhausted
        allowed_t1, _, _ = await bucket.consume("t1")
        self.assertFalse(allowed_t1)
        # t2 should be unaffected
        allowed_t2, _, _ = await bucket.consume("t2")
        self.assertTrue(allowed_t2)

    async def test_concurrent_access(self):
        """Multiple coroutines draining the same tenant don't over-consume."""
        bucket = LocalTokenBucket(capacity=10, refill_per_second=0.001)
        results = await asyncio.gather(
            *(bucket.consume("t1", cost=1) for _ in range(15))
        )
        allowed_count = sum(1 for allowed, _, _ in results if allowed)
        self.assertEqual(allowed_count, 10)

    async def test_cost_parameter(self):
        bucket = LocalTokenBucket(capacity=10, refill_per_second=0.0)
        allowed, remaining, _ = await bucket.consume("t1", cost=7)
        self.assertTrue(allowed)
        self.assertAlmostEqual(remaining, 3.0, delta=0.1)
        # 4 more should fail
        allowed, _, retry_after = await bucket.consume("t1", cost=4)
        self.assertFalse(allowed)
        self.assertNotEqual(retry_after, 0)

    async def test_reset_single_tenant(self):
        bucket = LocalTokenBucket(capacity=5, refill_per_second=0.0)
        for _ in range(5):
            await bucket.consume("t1")
        bucket.reset("t1")
        allowed, _, _ = await bucket.consume("t1")
        self.assertTrue(allowed)

    async def test_reset_all(self):
        bucket = LocalTokenBucket(capacity=5, refill_per_second=0.0)
        for _ in range(5):
            await bucket.consume("t1")
        for _ in range(5):
            await bucket.consume("t2")
        bucket.reset()
        allowed_t1, _, _ = await bucket.consume("t1")
        allowed_t2, _, _ = await bucket.consume("t2")
        self.assertTrue(allowed_t1)
        self.assertTrue(allowed_t2)

    async def test_retry_after_math(self):
        """retry_after_ms should reflect time needed to accumulate deficit."""
        bucket = LocalTokenBucket(capacity=5, refill_per_second=10.0)
        # Drain fully
        for _ in range(5):
            await bucket.consume("t1")
        _, _, retry_after = await bucket.consume("t1", cost=1)
        # Need 1 token at 10/sec → ~100ms
        self.assertGreater(retry_after, 50)
        self.assertLess(retry_after, 200)


if __name__ == "__main__":
    unittest.main()
