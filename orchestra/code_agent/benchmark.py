from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestra.code_agent import Agent, AgentConfig


@dataclass
class BenchmarkTask:
    name: str
    prompt: str
    expected: str | None = None
    timeout: int = 120
    setup_commands: list[str] = field(default_factory=list)
    cleanup_commands: list[str] = field(default_factory=list)


@dataclass
class BenchmarkResult:
    task_name: str
    passed: bool
    duration: float
    output: str
    iterations: int
    error: str | None = None


class Benchmark:
    def __init__(self, agent_config: AgentConfig | None = None):
        self.config = agent_config or AgentConfig(max_iterations=30)
        self.tasks: list[BenchmarkTask] = []

    def add_task(self, task: BenchmarkTask) -> None:
        self.tasks.append(task)

    async def run_all(self) -> list[BenchmarkResult]:
        results = []
        for task in self.tasks:
            r = await self._run_single(task)
            results.append(r)
            print(f"  {r.task_name}: {'PASS' if r.passed else 'FAIL'} ({r.duration:.1f}s)")
        return results

    async def _run_single(self, task: BenchmarkTask) -> BenchmarkResult:
        agent = Agent(self.config)

        for cmd in task.setup_commands:
            import subprocess
            subprocess.run(cmd, shell=True, capture_output=True)

        start = time.time()
        try:
            output = await asyncio.wait_for(agent.run(task.prompt), timeout=task.timeout)
        except asyncio.TimeoutError:
            output = "TIMEOUT"
        except Exception as e:
            output = f"ERROR: {e}"
        duration = time.time() - start

        for cmd in task.cleanup_commands:
            import subprocess
            subprocess.run(cmd, shell=True, capture_output=True)

        passed = True
        if task.expected and task.expected not in output:
            passed = False

        return BenchmarkResult(
            task_name=task.name,
            passed=passed,
            duration=duration,
            output=output,
            iterations=agent.state.iterations,
            error=None if passed else f"Expected '{task.expected}' not in output",
        )

    def report(self, results: list[BenchmarkResult]) -> str:
        total = len(results)
        passed = sum(1 for r in results if r.passed)
        avg_duration = sum(r.duration for r in results) / total if total else 0

        lines = [
            f"Benchmark Results: {passed}/{total} passed",
            f"Average duration: {avg_duration:.1f}s",
            "",
        ]
        for r in results:
            status = "PASS" if r.passed else "FAIL"
            lines.append(f"  [{status}] {r.task_name} ({r.duration:.1f}s, {r.iterations} iters)")
            if r.error:
                lines.append(f"         {r.error}")
        return "\n".join(lines)

    def save_json(self, results: list[BenchmarkResult], path: str) -> None:
        data = [
            {
                "task": r.task_name,
                "passed": r.passed,
                "duration": r.duration,
                "iterations": r.iterations,
                "error": r.error,
            }
            for r in results
        ]
        Path(path).write_text(json.dumps(data, indent=2), "utf-8")
