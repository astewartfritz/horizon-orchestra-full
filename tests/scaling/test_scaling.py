"""Tests for the scaling layer — Redis state, task queue, workers, scaling manager, circuit breaker, edge adapter."""
from __future__ import annotations

import asyncio
import time

import pytest

from code_agent.scaling.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from code_agent.scaling.scaling_manager import ScalingManager, ScalingConfig, ScalingAction
from code_agent.scaling.edge_adapter import EdgeAdapter, EdgeMode
from code_agent.scaling.task_queue import DistributedTaskQueue, QueuePriority, QueueTask
from code_agent.scaling.worker import Worker, WorkerPool


# ── Circuit Breaker ──

class TestCircuitBreaker:
    def test_initial_state(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_trips_on_failure_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3, reset_timeout=60)
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_half_open_on_reset_timeout(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False
        time.sleep(0.06)
        assert cb.allow_request() is True
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_on_half_open_success(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.06)
        cb.allow_request()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_reopens_on_half_open_failure(self):
        cb = CircuitBreaker(name="test", failure_threshold=2, reset_timeout=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        cb.allow_request()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_reset(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_summary(self):
        cb = CircuitBreaker(name="test")
        summary = cb.summary()
        assert summary["name"] == "test"
        assert summary["state"] == "closed"
        assert summary["is_open"] is False


class TestCircuitBreakerRegistry:
    def test_get_or_create(self):
        reg = CircuitBreakerRegistry()
        cb1 = reg.get("lane1", failure_threshold=3)
        cb2 = reg.get("lane1", failure_threshold=5)
        assert cb1 is cb2
        assert cb1.failure_threshold == 3

    def test_record_success_and_failure(self):
        reg = CircuitBreakerRegistry()
        reg.record_failure("lane1", failure_threshold=2)
        reg.record_failure("lane1", failure_threshold=2)
        cb = reg.get("lane1", failure_threshold=2)
        assert cb.state == CircuitState.OPEN

        reg.record_success("lane1")  # no-op while OPEN
        assert cb.state == CircuitState.OPEN

    def test_record_success_closes_half_open(self):
        reg = CircuitBreakerRegistry()
        reg.record_failure("test", failure_threshold=1)
        assert reg.get("test").state == CircuitState.OPEN
        reg.get("test")._transition(CircuitState.HALF_OPEN)
        reg.record_success("test")
        assert reg.get("test").state == CircuitState.CLOSED

    def test_allow_request_defaults(self):
        reg = CircuitBreakerRegistry()
        assert reg.allow_request("new_lane") is True

    def test_all_summaries(self):
        reg = CircuitBreakerRegistry()
        reg.get("a")
        reg.get("b")
        summaries = reg.all_summaries()
        assert "a" in summaries
        assert "b" in summaries

    def test_reset_all(self):
        reg = CircuitBreakerRegistry()
        reg.record_failure("x", failure_threshold=1)
        cb = reg.get("x", failure_threshold=1)
        assert cb.state == CircuitState.OPEN
        reg.reset_all()
        assert cb.state == CircuitState.CLOSED


# ── Scaling Manager ──

class TestScalingManager:
    @pytest.mark.asyncio
    async def test_hold_when_within_thresholds(self):
        sm = ScalingManager(ScalingConfig(min_workers=2, max_workers=10))
        decision = await sm.evaluate()
        assert decision.action == ScalingAction.HOLD
        assert decision.target_size == 2

    @pytest.mark.asyncio
    async def test_scale_up_when_queue_deep(self):
        sm = ScalingManager(
            ScalingConfig(min_workers=2, max_workers=10, scale_up_threshold=100),
            get_queue_depth=lambda: {"HIGH": 150},
            get_current_workers=lambda: 2,
        )
        decision = await sm.evaluate()
        assert decision.action == ScalingAction.SCALE_UP
        assert decision.target_size > 2

    @pytest.mark.asyncio
    async def test_scale_down_when_queue_shallow(self):
        sm = ScalingManager(
            ScalingConfig(min_workers=2, max_workers=10, scale_up_threshold=1000, scale_down_threshold=10),
            get_queue_depth=lambda: {"HIGH": 3},
            get_current_workers=lambda: 5,
        )
        decision = await sm.evaluate()
        assert decision.action == ScalingAction.SCALE_DOWN
        assert decision.target_size < 5

    @pytest.mark.asyncio
    async def test_respects_cooldown(self):
        sm = ScalingManager(
            ScalingConfig(min_workers=2, max_workers=10, scale_up_threshold=100, cooldown_seconds=60),
            get_queue_depth=lambda: {"HIGH": 200},
            get_current_workers=lambda: 2,
        )
        d1 = await sm.evaluate()
        assert d1.action == ScalingAction.SCALE_UP
        d2 = await sm.evaluate()
        assert d2.action == ScalingAction.HOLD

    @pytest.mark.asyncio
    async def test_emergency_stop_on_dlq(self):
        sm = ScalingManager(
            ScalingConfig(min_workers=2, max_workers=10, scale_up_threshold=100),
            get_queue_depth=lambda: {"HIGH": 300},
            get_dlq_count=lambda: 150,
            get_current_workers=lambda: 2,
        )
        decision = await sm.evaluate()
        assert decision.action == ScalingAction.EMERGENCY_STOP

    @pytest.mark.asyncio
    async def test_get_history(self):
        sm = ScalingManager(
            ScalingConfig(min_workers=2, max_workers=10, scale_up_threshold=100, cooldown_seconds=0),
            get_queue_depth=lambda: {"HIGH": 200},
            get_current_workers=lambda: 2,
        )
        await sm.evaluate()
        await sm.evaluate()
        assert len(sm.get_history(limit=10)) == 2


# ── Edge Adapter ──

class TestEdgeAdapter:
    @pytest.mark.asyncio
    async def test_mock_inference(self):
        adapter = EdgeAdapter(mode=EdgeMode.OFFLINE)
        result, error = await adapter.infer("test prompt", "reasoning")
        assert error is None
        assert result is not None
        assert "test prompt" in result

    @pytest.mark.asyncio
    async def test_cache_hits(self):
        adapter = EdgeAdapter(mode=EdgeMode.OFFLINE, enable_cache=True)
        r1, _ = await adapter.infer("hello", "general")
        r2, _ = await adapter.infer("hello", "general")
        assert r1 == r2
        assert adapter.cache_size == 1

    @pytest.mark.asyncio
    async def test_clear_cache(self):
        adapter = EdgeAdapter(mode=EdgeMode.OFFLINE, enable_cache=True)
        await adapter.infer("test", "general")
        assert adapter.cache_size == 1
        adapter.clear_cache()
        assert adapter.cache_size == 0

    @pytest.mark.asyncio
    async def test_ollama_infer_fallback_on_no_server(self):
        adapter = EdgeAdapter(
            mode=EdgeMode.OLLAMA,
            ollama_base_url="http://localhost:19999",
            ollama_model="test-model",
        )
        result, error = await adapter.infer("hello")
        assert result is None
        assert error is not None

    def test_cache_size_property(self):
        adapter = EdgeAdapter(mode=EdgeMode.OFFLINE)
        assert adapter.cache_size == 0

    @pytest.mark.asyncio
    async def test_privacy_mode(self):
        adapter = EdgeAdapter(mode=EdgeMode.PRIVACY)
        result, error = await adapter.infer("private data", "general")
        assert result is not None
        assert error is None


# ── Task Queue (no-Redis fallback) ──

class TestDistributedTaskQueue:
    @pytest.mark.asyncio
    async def test_enqueue_without_redis(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")
        task = QueueTask(user_input="test", intent="general")
        ok = await tq.enqueue(task)
        assert ok is False

    @pytest.mark.asyncio
    async def test_dequeue_without_redis(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")
        task = await tq.dequeue()
        assert task is None

    @pytest.mark.asyncio
    async def test_ack_without_redis(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")
        ok = await tq.ack("nonexistent")
        assert ok is False

    @pytest.mark.asyncio
    async def test_nack_without_redis(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")
        ok = await tq.nack("nonexistent")
        assert ok is False

    @pytest.mark.asyncio
    async def test_depth_without_redis(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")
        depth = await tq.depth()
        assert depth == {}

    @pytest.mark.asyncio
    async def test_processing_count_without_redis(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")
        count = await tq.processing_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_dlq_count_without_redis(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")
        count = await tq.dlq_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_is_backpressured(self):
        tq = DistributedTaskQueue(
            redis_url="redis://localhost:1",
            backpressure_threshold=100,
        )
        bp = await tq.is_backpressured()
        assert bp is False

    def test_queue_task_defaults(self):
        task = QueueTask(user_input="hello")
        assert task.status == "pending"
        assert task.retries == 0
        assert task.max_retries == 3
        assert task.priority == QueuePriority.MEDIUM

    def test_queue_priority_values(self):
        assert QueuePriority.CRITICAL.value == 0
        assert QueuePriority.HIGH.value == 1
        assert QueuePriority.MEDIUM.value == 2
        assert QueuePriority.LOW.value == 3
        assert QueuePriority.BACKGROUND.value == 4

    @pytest.mark.asyncio
    async def test_enqueue_rejects_when_full(self):
        tq = DistributedTaskQueue(
            redis_url="redis://localhost:1", max_queue_depth=0,
        )
        task = QueueTask(user_input="test")
        ok = await tq.enqueue(task)
        assert ok is False

    def test_queue_task_serialization_roundtrip(self):
        task = QueueTask(
            user_input="hello world",
            intent="code",
            priority=QueuePriority.HIGH,
            metadata={"user_id": "abc"},
        )
        raw = tq._serialize(task) if 'tq' in dir() else None
        tq_local = DistributedTaskQueue(redis_url="redis://localhost:1")
        raw = tq_local._serialize(task)
        restored = tq_local._deserialize(raw)
        assert restored.user_input == task.user_input
        assert restored.intent == task.intent
        assert restored.priority == task.priority
        assert restored.metadata == task.metadata

    @pytest.mark.asyncio
    async def test_deserialize_bad_json(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")
        assert tq._deserialize("not json") is None


# ── Worker ──

class TestWorker:
    def test_worker_defaults(self):
        w = Worker()
        assert w.status == "idle"
        assert w.task_count == 0
        assert w.error_count == 0
        assert len(w.worker_id) == 8

    def test_worker_lanes_default(self):
        w = Worker()
        assert w.lanes == ["general"]

    def test_worker_tracks_tasks(self):
        w = Worker()
        w.current_tasks.add("task1")
        assert len(w.current_tasks) == 1
        w.current_tasks.discard("task1")
        assert len(w.current_tasks) == 0


class TestWorkerPool:
    @pytest.mark.asyncio
    async def test_list_workers_without_redis(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")

        async def handler(task):
            return True, "ok", None

        pool = WorkerPool(tq, handler, redis_url="redis://localhost:1", pool_size=2)
        workers = await pool.list_workers()
        assert len(workers) == 0

    @pytest.mark.asyncio
    async def test_total_counts(self):
        tq = DistributedTaskQueue(redis_url="redis://localhost:1")

        async def handler(task):
            return True, "ok", None

        pool = WorkerPool(tq, handler, redis_url="redis://localhost:1", pool_size=3)
        assert pool.total_task_count == 0
        assert pool.total_error_count == 0
        assert len(pool.workers) == 0  # not started yet
