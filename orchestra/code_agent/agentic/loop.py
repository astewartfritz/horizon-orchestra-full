"""Generate → Review → Correct autonomous agent loop.

The system reads codebase, plans changes, writes code, runs tests,
inspects failures, and iterates until the change is valid.

Architecture:
1. Ingest repo context and relevant files
2. Generate a plan or proposed patch
3. Run tests or checks on the change
4. Detect failures, debug, and correct
5. Re-run validation before finalizing
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent import Agent, AgentConfig
from orchestra.code_agent.agentic.tester import TestRunner, TestResult
from orchestra.code_agent.human.steps import StepTracker


@dataclass
class GRCIteration:
    iteration: int
    plan: str = ""
    patch: str = ""
    test_results: list[TestResult] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    corrections: list[str] = field(default_factory=list)
    passed: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "plan": self.plan[:200],
            "patch": self.patch[:200],
            "test_count": len(self.test_results),
            "failures": self.failures[:3],
            "corrections": self.corrections[:3],
            "passed": self.passed,
            "duration_ms": self.duration_ms,
        }


class GRCLoop:
    """Generate-Review-Correct autonomous loop.

    The feedback loop is what makes the system agentic rather than
    one-shot: generation is immediately followed by evaluation,
    and evaluation can trigger correction.
    """

    def __init__(self, config: AgentConfig | None = None, max_iterations: int = 5,
                 test_command: str = "python -m pytest -x -q"):
        self.config = config or AgentConfig()
        self.max_iterations = max_iterations
        self.test_command = test_command
        self.steps = StepTracker()
        self.tester = TestRunner(test_command)
        self._iterations: list[GRCIteration] = []
        self.logger = logging.getLogger("orchestra.grc")

    async def run(self, task: str) -> dict[str, Any]:
        """Run the full GRC loop on a task."""
        start = time.time()
        self.logger.info("GRC starting: %s", task[:100])
        self.steps.record("task", f"GRC task: {task[:80]}")

        agent = Agent(self.config)

        for i in range(1, self.max_iterations + 1):
            iteration = GRCIteration(iteration=i)
            iter_start = time.time()
            self.logger.info("GRC iteration %d/%d", i, self.max_iterations)

            # 1. Generate: agent reads codebase, plans, writes code
            result = await agent.run(
                f"{task}\n\nThis is iteration {i}. "
                f"{'Previous attempt had failures: ' + '; '.join(self._iterations[-1].failures) if self._iterations else ''}"
                f"{'Previous corrections applied: ' + '; '.join(self._iterations[-1].corrections) if self._iterations else ''}"
                f"\n\nAfter making changes, I will run: {self.test_command}",
                stream=True,
            )
            iteration.plan = result[:500] if result else ""
            self.steps.record("generate", f"Iteration {i}: generated changes")

            # 2. Review: run tests
            test_results = await self.tester.run()
            iteration.test_results = test_results
            failures = [r for r in test_results if not r.passed]
            iteration.failures = [f.name for f in failures[:5]]
            iteration.passed = len(failures) == 0
            iteration.duration_ms = int((time.time() - iter_start) * 1000)

            if iteration.passed:
                self.logger.info("GRC iteration %d PASSED", i)
                self._iterations.append(iteration)
                self.steps.record("pass", f"Iteration {i}: all tests passed")
                break

            # 3. Correct: analyze failures and guide next iteration
            if i < self.max_iterations:
                corrections = await self._correct(failures, agent)
                iteration.corrections = corrections
                self.steps.record("correct", f"Iteration {i}: correcting {len(failures)} failures")
                self.logger.info("GRC iteration %d: %d failures, correcting", i, len(failures))

            self._iterations.append(iteration)

        total_ms = int((time.time() - start) * 1000)
        final = self._iterations[-1] if self._iterations else None

        return {
            "task": task,
            "iterations": len(self._iterations),
            "passed": final.passed if final else False,
            "total_duration_ms": total_ms,
            "iterations_detail": [it.to_dict() for it in self._iterations],
        }

    async def _correct(self, failures: list[TestResult], agent: Agent) -> list[str]:
        """Analyze test failures and guide the next iteration."""
        corrections = []
        for failure in failures[:3]:
            analysis = await agent.run(
                f"A test failed:\n{failure.name}\nError: {failure.error or 'No output'}\n"
                f"Output: {(failure.output or '')[:500]}\n\n"
                f"Analyze the root cause and suggest a specific fix.",
                stream=True,
            )
            corrections.append(analysis[:300] if analysis else "")
        return corrections

    def get_history(self) -> list[dict[str, Any]]:
        return [it.to_dict() for it in self._iterations]
