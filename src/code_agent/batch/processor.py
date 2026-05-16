from __future__ import annotations

import asyncio
import csv
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

from code_agent.agent import Agent
from code_agent.config import AgentConfig


@dataclass
class BatchTask:
    id: str = ""
    task: str = ""
    model: str = "gpt-4o-mini"
    max_iterations: int = 10
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class BatchResult:
    id: str = ""
    status: str = "pending"
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0
    tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BatchProcessor:
    """Process multiple tasks in parallel with concurrency control."""

    def __init__(self, max_concurrency: int = 5):
        self.max_concurrency = max_concurrency
        self._semaphore = asyncio.Semaphore(max_concurrency)

    async def process(self, tasks: list[BatchTask]) -> list[BatchResult]:
        async def run_one(task: BatchTask) -> BatchResult:
            async with self._semaphore:
                start = time.time()
                try:
                    llm_cfg = __import__("code_agent.config", fromlist=[""]).LLMConfig(
                        provider="openai", model=task.model
                    )
                    cfg = AgentConfig(llm=llm_cfg, max_iterations=task.max_iterations, name=task.id)
                    agent = Agent(cfg)
                    output = await agent.run(task.task)
                    duration = (time.time() - start) * 1000
                    return BatchResult(
                        id=task.id, status="success",
                        output=output[:2000], duration_ms=round(duration, 1),
                    )
                except Exception as e:
                    duration = (time.time() - start) * 1000
                    return BatchResult(
                        id=task.id, status="error",
                        error=str(e)[:500], duration_ms=round(duration, 1),
                    )

        tasks_coro = [run_one(t) for t in tasks]
        return await asyncio.gather(*tasks_coro)

    @staticmethod
    def from_json(path: str) -> list[BatchTask]:
        data = json.loads(Path(path).read_text())
        return [BatchTask(**t) for t in data]

    @staticmethod
    def from_csv(path: str) -> list[BatchTask]:
        tasks = []
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                tasks.append(BatchTask(**row))
        return tasks

    @staticmethod
    def save_results(results: list[BatchResult], path: str) -> None:
        data = [r.to_dict() for r in results]
        Path(path).write_text(json.dumps(data, indent=2))

    def summary(self, results: list[BatchResult]) -> dict[str, Any]:
        total = len(results)
        success = sum(1 for r in results if r.status == "success")
        failed = sum(1 for r in results if r.status == "error")
        total_duration = sum(r.duration_ms for r in results)
        return {
            "total": total, "success": success, "failed": failed,
            "total_duration_ms": round(total_duration, 1),
            "avg_duration_ms": round(total_duration / total, 1) if total else 0,
        }
