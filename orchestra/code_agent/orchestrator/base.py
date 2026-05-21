from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from orchestra.code_agent import Agent, AgentConfig


class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    description: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    agent_config: AgentConfig | None = None
    dependencies: list[str] = field(default_factory=list)


@dataclass
class TaskResult:
    task_id: str
    status: TaskStatus
    result: str | None = None
    error: str | None = None


class Orchestrator:
    def __init__(self, default_config: AgentConfig | None = None):
        self.default_config = default_config or AgentConfig()
        self.tasks: dict[str, Task] = {}
        self._results: dict[str, TaskResult] = {}
        self._agents: dict[str, Agent] = {}

    def add_task(self, task: Task) -> str:
        self.tasks[task.id] = task
        return task.id

    async def run_task(self, task_id: str) -> TaskResult:
        task = self.tasks[task_id]
        task.status = TaskStatus.RUNNING

        config = task.agent_config or self.default_config
        agent = Agent(config)
        self._agents[task_id] = agent

        try:
            result = await agent.run(task.prompt)
            task.status = TaskStatus.COMPLETED
            task.result = result
            tr = TaskResult(task_id, TaskStatus.COMPLETED, result=result)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            tr = TaskResult(task_id, TaskStatus.FAILED, error=str(e))

        self._results[task_id] = tr
        return tr

    async def get_result(self, task_id: str) -> TaskResult | None:
        return self._results.get(task_id)


class SequentialOrchestrator(Orchestrator):
    async def run_all(self) -> list[TaskResult]:
        results = []
        for tid in self.tasks:
            tr = await self.run_task(tid)
            results.append(tr)
        return results


class ParallelOrchestrator(Orchestrator):
    async def run_all(self, max_concurrent: int = 5) -> list[TaskResult]:
        sem = asyncio.Semaphore(max_concurrent)

        async def _run(tid: str) -> TaskResult:
            async with sem:
                return await self.run_task(tid)

        tasks = [asyncio.create_task(_run(tid)) for tid in self.tasks]
        return await asyncio.gather(*tasks)

    async def run_map(
        self, prompt_template: str, items: list[Any],
        item_name: str = "item",
        max_concurrent: int = 5,
    ) -> list[TaskResult]:
        for i, item in enumerate(items):
            tid = f"item_{i}"
            prompt = prompt_template.replace(f"{{{item_name}}}", str(item))
            self.add_task(Task(id=tid, description=str(item), prompt=prompt))
        return await self.run_all(max_concurrent)


class VotingOrchestrator(Orchestrator):
    def __init__(self, default_config: AgentConfig | None = None, num_voters: int = 3):
        super().__init__(default_config)
        self.num_voters = num_voters

    async def run_with_vote(self, prompt: str, aggregator: Callable[[list[str]], str] | None = None) -> str:
        for i in range(self.num_voters):
            tid = f"voter_{i}"
            self.add_task(Task(
                id=tid,
                description=f"Voter {i}: {prompt[:50]}",
                prompt=prompt,
            ))

        results = []
        for tid in list(self.tasks.keys()):
            tr = await self.run_task(tid)
            if tr.result:
                results.append(tr.result)

        if not results:
            return "No results from voters"

        if aggregator:
            return aggregator(results)

        counts: dict[str, int] = {}
        for r in results:
            counts[r] = counts.get(r, 0) + 1
        return max(counts, key=counts.get)
