"""Tests for scheduling system (cron, DAG, store, engine)."""

import asyncio
import os
import time
from pathlib import Path

import pytest

from code_agent.scheduler import (
    CronExpr,
    RetryPolicy,
    ScheduledTask,
    SchedulerEngine,
    SchedulerStore,
    TaskDAG,
    TaskStatus,
)

TEST_SCHEDULER_DB = ".test-agent-scheduler.db"


def _fresh_db():
    return f".test-sch-{os.getpid()}-{time.time_ns()}.db"


def setup_function():
    Path(TEST_SCHEDULER_DB).unlink(missing_ok=True)


def teardown_function():
    Path(TEST_SCHEDULER_DB).unlink(missing_ok=True)


class TestCronExpr:
    def test_every_minute(self):
        c = CronExpr("* * * * *")
        now = time.time()
        next_t = c.next_match()
        assert next_t.timestamp() >= now - 1

    def test_every_hour(self):
        c = CronExpr("0 * * * *")
        n = c.next_match()
        assert n.minute == 0

    def test_specific_hour(self):
        c = CronExpr("30 9 * * *")
        n = c.next_match()
        assert n.minute == 30

    def test_weekday(self):
        c = CronExpr("0 9 * * 1-5")
        n = c.next_match()
        assert n.weekday() in range(0, 5)

    def test_step(self):
        c = CronExpr("*/15 * * * *")
        n = c.next_match()
        assert n.minute % 15 == 0

    def test_invalid_expression(self):
        import pytest
        with pytest.raises(ValueError):
            CronExpr("invalid")
        with pytest.raises(ValueError):
            CronExpr("* * *")


class TestRetryPolicy:
    def test_exponential_backoff(self):
        rp = RetryPolicy(max_retries=3, base_delay_seconds=2, backoff_multiplier=2, max_delay_seconds=30)
        assert rp.delay(0) == 2
        assert rp.delay(1) == 4
        assert rp.delay(2) == 8

    def test_max_delay_cap(self):
        rp = RetryPolicy(max_retries=5, base_delay_seconds=10, backoff_multiplier=10, max_delay_seconds=30)
        assert rp.delay(0) == 10
        assert rp.delay(1) == 30
        assert rp.delay(2) == 30


class TestTaskDAG:
    def test_add_dependency(self):
        dag = TaskDAG()
        dag.add_dependency("task_b", "task_a")
        assert dag.get_dependencies("task_b") == {"task_a"}

    def test_is_ready(self):
        dag = TaskDAG()
        dag.add_dependency("b", "a")
        assert not dag.is_ready("b", set())
        assert dag.is_ready("b", {"a"})
        assert dag.is_ready("a", set())

    def test_topological_sort(self):
        dag = TaskDAG()
        dag.add_dependency("c", "a")
        dag.add_dependency("c", "b")
        dag.add_dependency("b", "a")
        order = dag.topological_sort({"a", "b", "c"})
        assert order.index("a") < order.index("b")
        assert order.index("b") < order.index("c")

    def test_get_dependents(self):
        dag = TaskDAG()
        dag.add_dependency("a", "base")
        dag.add_dependency("b", "base")
        deps = dag.get_dependents("base")
        assert sorted(deps) == ["a", "b"]

    def test_remove_dependency(self):
        dag = TaskDAG()
        dag.add_dependency("a", "b")
        dag.remove_dependency("a", "b")
        assert dag.get_dependencies("a") == set()


class TestSchedulerStore:
    def test_save_and_load_task(self):
        db = _fresh_db()
        store = SchedulerStore(db)
        try:
            task = ScheduledTask(name="test", task="echo hello", interval_seconds=60)
            store.save_task(task)
            loaded = store.load_task("test")
            assert loaded is not None
            assert loaded.name == "test"
            assert loaded.task == "echo hello"
            assert loaded.interval_seconds == 60
        finally:
            store.close()
            Path(db).unlink(missing_ok=True)

    def test_load_all(self):
        db = _fresh_db()
        store = SchedulerStore(db)
        try:
            t1 = ScheduledTask(name="a", task="task a", interval_seconds=60)
            t2 = ScheduledTask(name="b", task="task b", interval_seconds=120)
            store.save_task(t1)
            store.save_task(t2)
            tasks = store.load_all()
            assert len(tasks) == 2
        finally:
            store.close()
            Path(db).unlink(missing_ok=True)

    def test_delete_task(self):
        db = _fresh_db()
        store = SchedulerStore(db)
        try:
            t = ScheduledTask(name="del_test", task="delete me", interval_seconds=60)
            store.save_task(t)
            assert store.delete_task("del_test") is True
            assert store.load_task("del_test") is None
        finally:
            store.close()
            Path(db).unlink(missing_ok=True)

    def test_update_status(self):
        db = _fresh_db()
        store = SchedulerStore(db)
        try:
            t = ScheduledTask(name="status_test", task="test", interval_seconds=60)
            store.save_task(t)
            store.update_status("status_test", TaskStatus.RUNNING)
            loaded = store.load_task("status_test")
            assert loaded.status == TaskStatus.RUNNING
        finally:
            store.close()
            Path(db).unlink(missing_ok=True)

    def test_dependencies(self):
        db = _fresh_db()
        store = SchedulerStore(db)
        try:
            store.add_dependency("task_b", "task_a")
            deps = store.get_dependencies("task_b")
            assert "task_a" in deps
        finally:
            store.close()
            Path(db).unlink(missing_ok=True)

    def test_task_history(self):
        db = _fresh_db()
        store = SchedulerStore(db)
        try:
            entry = {
                "task_name": "hist_test",
                "status": "completed",
                "started_at": time.time() - 10,
                "finished_at": time.time(),
                "duration_ms": 500,
                "attempt": 1,
                "error": "",
                "output": "ok",
                "created_at": time.time(),
            }
            store.save_history(entry)
            history = store.load_history(task_name="hist_test")
            assert len(history) >= 1
        finally:
            store.close()
            Path(db).unlink(missing_ok=True)

    def test_task_stats(self):
        db = _fresh_db()
        store = SchedulerStore(db)
        try:
            t = ScheduledTask(name="stats_test", task="test", interval_seconds=60)
            store.save_task(t)
            stats = store.task_stats("stats_test")
            assert "total" in stats
        finally:
            store.close()
            Path(db).unlink(missing_ok=True)

    def test_load_due(self):
        db = _fresh_db()
        store = SchedulerStore(db)
        try:
            past = ScheduledTask(name="past_task", task="old", interval_seconds=60)
            past.next_run = time.time() - 10
            past.status = TaskStatus.PENDING
            past.enabled = True
            store.save_task(past)
            due = store.load_due(time.time())
            names = [t.name for t in due]
            assert "past_task" in names
        finally:
            store.close()
            Path(db).unlink(missing_ok=True)


class TestSchedulerEngine:
    @pytest.mark.asyncio
    async def test_add_and_list(self):
        db = _fresh_db()
        engine = SchedulerEngine(SchedulerStore(db))
        try:
            t = ScheduledTask(name="e_test", task="hello", interval_seconds=60)
            engine.add_task(t)
            tasks = engine.list_tasks()
            assert any(t.name == "e_test" for t in tasks)
        finally:
            engine.close()
            Path(db).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_pause_resume(self):
        db = _fresh_db()
        engine = SchedulerEngine(SchedulerStore(db))
        try:
            t = ScheduledTask(name="pr_test", task="test", interval_seconds=60)
            engine.add_task(t)
            assert engine.pause_task("pr_test") is True
            task = engine.get_task("pr_test")
            assert task.enabled is False
            assert engine.resume_task("pr_test") is True
            task = engine.get_task("pr_test")
            assert task.enabled is True
        finally:
            engine.close()
            Path(db).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_remove_task(self):
        db = _fresh_db()
        engine = SchedulerEngine(SchedulerStore(db))
        try:
            t = ScheduledTask(name="rm_test", task="test", interval_seconds=60)
            engine.add_task(t)
            assert engine.remove_task("rm_test") is True
            assert engine.get_task("rm_test") is None
        finally:
            engine.close()
            Path(db).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_get_nonexistent(self):
        engine = SchedulerEngine(SchedulerStore(_fresh_db()))
        assert engine.get_task("nonexistent") is None

    @pytest.mark.asyncio
    async def test_pause_nonexistent(self):
        engine = SchedulerEngine(SchedulerStore(_fresh_db()))
        assert engine.pause_task("no_such_task") is False

    @pytest.mark.asyncio
    async def test_start_stop(self):
        db = _fresh_db()
        engine = SchedulerEngine(SchedulerStore(db))
        try:
            engine.start()
            await asyncio.sleep(0.1)
            assert engine._running is True
            engine.stop()
            assert engine._running is False
        finally:
            engine.close()
            Path(db).unlink(missing_ok=True)

    @pytest.mark.asyncio
    async def test_with_health_checker(self):
        """Engine accepts optional health_checker without crashing."""
        db = _fresh_db()
        engine = SchedulerEngine(SchedulerStore(db), health_checker=object())
        try:
            t = ScheduledTask(name="hc_test", task="hello", interval_seconds=60)
            engine.add_task(t)
            tasks = engine.list_tasks()
            assert any(t.name == "hc_test" for t in tasks)
        finally:
            engine.close()
            Path(db).unlink(missing_ok=True)

    def test_task_provider_default(self):
        t = ScheduledTask(name="prov_test", task="test", interval_seconds=60)
        assert t.provider == "ollama"

    def test_task_provider_custom(self):
        t = ScheduledTask(name="prov_test2", task="test", interval_seconds=60, provider="openai")
        assert t.provider == "openai"
