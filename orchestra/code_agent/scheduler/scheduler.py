from __future__ import annotations

import asyncio
from typing import Any, Callable

from orchestra.code_agent.scheduler.base import ScheduledTask, TaskStatus
from orchestra.code_agent.scheduler.engine import SchedulerEngine
from orchestra.code_agent.scheduler.store import SchedulerStore


class AgentScheduler:
    """Backward-compatible wrapper around SchedulerEngine.

    Maintains the original API: add(), remove(), list(), pause(), resume(),
    on(), run_forever(), stop().
    """

    def __init__(self, storage_path: str = ".agent-scheduler.json"):
        self._store = SchedulerStore()
        self._engine = SchedulerEngine(self._store)
        self._legacy_path = storage_path

    def add(self, task: ScheduledTask) -> None:
        self._engine.add_task(task)

    def remove(self, name: str) -> bool:
        return self._engine.remove_task(name)

    def list(self) -> list[ScheduledTask]:
        return self._engine.list_tasks()

    def pause(self, name: str) -> bool:
        return self._engine.pause_task(name)

    def resume(self, name: str) -> bool:
        return self._engine.resume_task(name)

    def on(self, event: str, handler: Callable) -> None:
        self._engine.on(event, handler)

    async def run_forever(self, tick_seconds: int = 10) -> None:
        self._engine.start()
        while self._engine._running:
            await asyncio.sleep(tick_seconds)
        self._engine.stop()

    def stop(self) -> None:
        self._engine.stop()

    @property
    def engine(self) -> SchedulerEngine:
        return self._engine
