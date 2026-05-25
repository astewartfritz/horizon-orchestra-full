"""Tests for the RateLimitMiddleware — allow/throttle decisions and breaker fallback."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from orchestra.middleware._breaker import BreakerState, CircuitBreaker
from orchestra.middleware._bucket import LocalTokenBucket
from orchestra.middleware.rate_limit import (
    AuditSink,
    RateLimitDecision,
    RateLimitMiddleware,
    RateLimitOptions,
    OrchestraMiddleware,
)


class _MockAuditSink:
    """Captures audit events for assertion."""

    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_type: str, payload: dict) -> None:
        self.events.append((event_type, payload))


class TestRateLimitMiddleware(unittest.IsolatedAsyncioTestCase):
    """Core middleware behavior with mock Redis."""

    def setUp(self):
        import os
        self._orig = os.environ.get("RATE_LIMIT_ENABLED")
        os.environ["RATE_LIMIT_ENABLED"] = "true"

    def tearDown(self):
        import os
        if self._orig is None:
            os.environ.pop("RATE_LIMIT_ENABLED", None)
        else:
            os.environ["RATE_LIMIT_ENABLED"] = self._orig

    async def test_allow_decision_with_mock_redis(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(return_value=[1, 9, 0])
        mw = RateLimitMiddleware(redis=redis)
        opts = RateLimitOptions(tenant_id="t1", capacity=10)
        decision = await mw.check(opts)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "redis")
        self.assertEqual(decision.remaining, 9.0)

    async def test_throttle_decision_with_mock_redis(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(return_value=[0, 0, 500])
        mw = RateLimitMiddleware(redis=redis)
        decision = await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.retry_after_ms, 500)
        self.assertEqual(decision.source, "redis")

    async def test_evalsha_noscript_fallback(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(side_effect=Exception("NOSCRIPT No matching script"))
        redis.eval = AsyncMock(return_value=[1, 5, 0])
        mw = RateLimitMiddleware(redis=redis)
        decision = await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "redis")
        redis.eval.assert_called_once()

    async def test_redis_failure_falls_back_to_memory(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(side_effect=ConnectionError("Connection refused"))
        breaker = CircuitBreaker(failure_threshold=1)
        mw = RateLimitMiddleware(redis=redis, breaker=breaker)

        # First call fails redis and opens breaker
        decision = await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "memory")

    async def test_breaker_open_uses_memory(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(side_effect=ConnectionError("down"))
        breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=999)
        mw = RateLimitMiddleware(redis=redis, breaker=breaker)

        # Trip the breaker
        await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertEqual(breaker.state, BreakerState.OPEN)

        # Subsequent calls should skip Redis entirely
        redis.evalsha.reset_mock()
        decision = await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertEqual(decision.source, "memory")
        redis.evalsha.assert_not_called()

    async def test_no_redis_uses_memory(self):
        mw = RateLimitMiddleware(redis=None)
        decision = await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "memory")

    async def test_audit_events_emitted(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(return_value=[1, 9, 0])
        sink = _MockAuditSink()
        mw = RateLimitMiddleware(redis=redis, audit_sink=sink)

        await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertEqual(len(sink.events), 1)
        self.assertEqual(sink.events[0][0], "rate_limit.allowed")
        self.assertEqual(sink.events[0][1]["tenant_id"], "t1")

    async def test_throttle_audit_event(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(return_value=[0, 0, 200])
        sink = _MockAuditSink()
        mw = RateLimitMiddleware(redis=redis, audit_sink=sink)

        await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertEqual(sink.events[0][0], "rate_limit.throttled")

    async def test_breaker_opened_audit_event(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(side_effect=ConnectionError("down"))
        sink = _MockAuditSink()
        breaker = CircuitBreaker(failure_threshold=1)
        mw = RateLimitMiddleware(redis=redis, breaker=breaker, audit_sink=sink)

        await mw.check(RateLimitOptions(tenant_id="t1"))
        event_types = [e[0] for e in sink.events]
        self.assertIn("rate_limit.breaker_opened", event_types)

    @patch.dict("os.environ", {"RATE_LIMIT_ENABLED": "false"})
    async def test_disabled_via_env(self):
        mw = RateLimitMiddleware(redis=None)
        decision = await mw.check(RateLimitOptions(tenant_id="t1"))
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.source, "disabled")


class TestMiddlewareProtocol(unittest.IsolatedAsyncioTestCase):
    """Test the before/after/on_error protocol hooks."""

    def setUp(self):
        import os
        self._orig = os.environ.get("RATE_LIMIT_ENABLED")
        os.environ["RATE_LIMIT_ENABLED"] = "true"

    def tearDown(self):
        import os
        if self._orig is None:
            os.environ.pop("RATE_LIMIT_ENABLED", None)
        else:
            os.environ["RATE_LIMIT_ENABLED"] = self._orig

    async def test_before_allows(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(return_value=[1, 9, 0])
        mw = RateLimitMiddleware(redis=redis)
        ctx = {"tenant_id": "t1"}
        result = await mw.before(ctx)
        self.assertIsNotNone(result)
        self.assertIn("rate_limit_decision", result)
        self.assertTrue(result["rate_limit_decision"].allowed)

    async def test_before_blocks_when_throttled(self):
        redis = AsyncMock()
        redis.evalsha = AsyncMock(return_value=[0, 0, 300])
        mw = RateLimitMiddleware(redis=redis)
        ctx = {"tenant_id": "t1"}
        result = await mw.before(ctx)
        self.assertIsNone(result)

    async def test_after_passthrough(self):
        mw = RateLimitMiddleware(redis=None)
        result = await mw.after({"tenant_id": "t1"}, "some_result")
        self.assertEqual(result, "some_result")

    async def test_on_error_reraises(self):
        mw = RateLimitMiddleware(redis=None)
        with self.assertRaises(ValueError):
            await mw.on_error({}, ValueError("test"))

    async def test_conforms_to_protocol(self):
        mw = RateLimitMiddleware(redis=None)
        self.assertIsInstance(mw, OrchestraMiddleware)


class TestFairnessMultiTenant(unittest.IsolatedAsyncioTestCase):
    """Concurrent requests from multiple tenants — no cross-tenant leakage."""

    def setUp(self):
        import os
        self._orig = os.environ.get("RATE_LIMIT_ENABLED")
        os.environ["RATE_LIMIT_ENABLED"] = "true"

    def tearDown(self):
        import os
        if self._orig is None:
            os.environ.pop("RATE_LIMIT_ENABLED", None)
        else:
            os.environ["RATE_LIMIT_ENABLED"] = self._orig

    async def test_no_cross_tenant_leakage(self):
        mw = RateLimitMiddleware(redis=None, default_capacity=10, default_refill_per_second=0.001)
        tenants = [f"tenant-{i}" for i in range(5)]
        results: dict[str, list[bool]] = {t: [] for t in tenants}

        async def flood(tenant: str):
            for _ in range(15):
                d = await mw.check(RateLimitOptions(tenant_id=tenant, capacity=10, refill_per_second=0.001))
                results[tenant].append(d.allowed)

        await asyncio.gather(*(flood(t) for t in tenants))

        for tenant in tenants:
            allowed_count = sum(1 for a in results[tenant] if a)
            self.assertEqual(allowed_count, 10, f"{tenant} got {allowed_count} instead of 10")


if __name__ == "__main__":
    unittest.main()
