from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any, Callable

from code_agent.scheduler.base import RetryPolicy, ScheduledTask, TaskDAG, TaskStatus
from code_agent.scheduler.store import SchedulerStore

try:
    from code_agent.serving.health import ModelHealthChecker
except ImportError:
    ModelHealthChecker = None  # type: ignore

TaskHandler = Callable[[ScheduledTask], Any]


class SchedulerEngine:
    """Async scheduler engine with cron, DAG, retry, and parallel execution."""

    def __init__(self, store: SchedulerStore | None = None, health_checker: ModelHealthChecker | None = None):
        self.store = store or SchedulerStore()
        self.health_checker = health_checker
        self.dag = TaskDAG()
        self._running = False
        self._tick_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()
        self._handlers: dict[str, list[Callable]] = {
            "before_run": [],
            "after_run": [],
            "error": [],
            "skipped": [],
        }
        self._custom_handler: TaskHandler | None = None
        self._refresh_dag()

    def on(self, event: str, handler: Callable) -> None:
        if event in self._handlers:
            self._handlers[event].append(handler)

    def set_task_handler(self, handler: TaskHandler) -> None:
        self._custom_handler = handler

    def _refresh_dag(self) -> None:
        tasks = self.store.load_all()
        task_names = {t.name for t in tasks}
        self.dag = TaskDAG()
        for t in tasks:
            for dep in self.store.get_dependencies(t.name):
                if dep in task_names:
                    self.dag.add_dependency(t.name, dep)

    def add_task(self, task: ScheduledTask) -> None:
        if not task.next_run:
            task.compute_next_run()
        task.status = TaskStatus.PENDING
        self.store.save_task(task)
        self._refresh_dag()

    def remove_task(self, name: str) -> bool:
        self._refresh_dag()
        return self.store.delete_task(name)

    def list_tasks(self) -> list[ScheduledTask]:
        return self.store.load_all()

    def get_task(self, name: str) -> ScheduledTask | None:
        return self.store.load_task(name)

    def pause_task(self, name: str) -> bool:
        task = self.store.load_task(name)
        if not task:
            return False
        task.enabled = False
        self.store.save_task(task)
        return True

    def resume_task(self, name: str) -> bool:
        task = self.store.load_task(name)
        if not task:
            return False
        task.enabled = True
        if not task.next_run or task.next_run < time.time():
            task.compute_next_run()
        self.store.save_task(task)
        return True

    def run_now(self, name: str) -> bool:
        task = self.store.load_task(name)
        if not task:
            return False
        asyncio.create_task(self._execute_task(task))
        return True

    def add_dependency(self, task_name: str, depends_on: str) -> None:
        self.store.add_dependency(task_name, depends_on)
        self._refresh_dag()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop())

    def stop(self) -> None:
        self._running = False
        if self._tick_task:
            self._tick_task.cancel()
            self._tick_task = None

    def close(self) -> None:
        self.stop()
        self.store.close()

    async def _tick_loop(self) -> None:
        while self._running:
            try:
                await self._process_due_tasks()
            except Exception:
                pass
            await asyncio.sleep(5)

    async def _process_due_tasks(self) -> None:
        now = time.time()
        due = self.store.load_due(now)
        if not due:
            return

        completed: set[str] = set()
        pending = {t.name for t in due if t.enabled}
        ordered = self.dag.topological_sort(pending)

        async def try_execute(task_name: str) -> None:
            if not self.dag.is_ready(task_name, completed):
                return
            task = self.store.load_task(task_name)
            if not task or not task.enabled:
                return
            if self.health_checker and not self.health_checker.is_provider_healthy(task.provider):
                task.status = TaskStatus.SKIPPED
                task.last_error = f"Provider '{task.provider}' is unhealthy"
                self.store.update_status(task_name, TaskStatus.SKIPPED, last_error=task.last_error)
                for cb in self._handlers.get("skipped", []):
                    cb(task)
                completed.add(task_name)
                return
            task.status = TaskStatus.RUNNING
            self.store.update_status(task_name, TaskStatus.RUNNING)
            await self._execute_task(task)
            completed.add(task_name)

        for task_name in ordered:
            if task_name in pending:
                await try_execute(task_name)

    async def _execute_task(self, task: ScheduledTask) -> None:
        started_at = time.time()
        attempt = 0
        max_attempts = (task.retry_policy.max_retries + 1) if task.retry_policy else 1
        last_error = ""

        for cb in self._handlers.get("before_run", []):
            cb(task)

        while attempt < max_attempts:
            attempt += 1
            try:
                result = await self._run_with_timeout(task, task.timeout_seconds)
                task.status = TaskStatus.COMPLETED
                task.run_count += 1
                task.success_count += 1
                task.last_run = time.time()
                task.compute_next_run(datetime.fromtimestamp(task.last_run))
                task.last_error = ""
                self.store.update_status(
                    task.name, TaskStatus.COMPLETED,
                    last_run=task.last_run, next_run=task.next_run,
                    run_count=task.run_count, success_count=task.success_count,
                    last_error="",
                )
                self.store.save_history({
                    "task_name": task.name,
                    "status": "completed",
                    "started_at": started_at,
                    "finished_at": time.time(),
                    "duration_ms": (time.time() - started_at) * 1000,
                    "attempt": attempt,
                    "error": "",
                    "output": str(result)[:5000] if result else "",
                    "created_at": time.time(),
                })
                for cb in self._handlers.get("after_run", []):
                    cb(task)
                return

            except asyncio.TimeoutError:
                last_error = f"Timeout after {task.timeout_seconds}s"
                if attempt >= max_attempts:
                    break
                delay = task.retry_policy.delay(attempt - 1) if task.retry_policy else 5
                await asyncio.sleep(delay)

            except Exception as e:
                last_error = str(e)
                if attempt >= max_attempts:
                    break
                delay = task.retry_policy.delay(attempt - 1) if task.retry_policy else 5
                await asyncio.sleep(delay)

        task.status = TaskStatus.FAILED
        task.run_count += 1
        task.failure_count += 1
        task.last_run = time.time()
        task.last_error = last_error[:1000]
        task.compute_next_run()
        self.store.update_status(
            task.name, TaskStatus.FAILED,
            last_run=task.last_run, next_run=task.next_run,
            run_count=task.run_count, failure_count=task.failure_count,
            last_error=task.last_error,
        )
        self.store.save_history({
            "task_name": task.name,
            "status": "failed",
            "started_at": started_at,
            "finished_at": time.time(),
            "duration_ms": (time.time() - started_at) * 1000,
            "attempt": attempt,
            "error": last_error[:5000],
            "output": "",
            "created_at": time.time(),
        })
        for cb in self._handlers.get("error", []):
            cb(task, last_error)

    async def _run_with_timeout(self, task: ScheduledTask, timeout: float) -> Any:
        async def _run() -> Any:
            if self._custom_handler:
                return await self._custom_handler(task)
            from code_agent.agent import Agent
            from code_agent.config import AgentConfig, LLMConfig, ReasoningConfig
            from code_agent.profiles.base import load_profile
            cfg = load_profile(task.profile)
            if cfg is None:
                cfg = AgentConfig(llm=LLMConfig(provider="ollama"), max_iterations=3)
            agent = Agent(cfg)
            return await agent.run(task.task)

        return await asyncio.wait_for(_run(), timeout=timeout)
