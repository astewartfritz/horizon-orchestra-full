from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from orchestra.code_agent.agent import Agent
from orchestra.code_agent.config import AgentConfig


class StepStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class WorkflowStep:
    id: str
    name: str
    prompt: str
    depends_on: list[str] = field(default_factory=list)
    agent_config: AgentConfig | None = None
    status: StepStatus = StepStatus.PENDING
    result: str | None = None
    error: str | None = None
    max_retries: int = 1
    timeout: int = 300
    condition: str | None = None  # Python expression to evaluate


@dataclass
class Workflow:
    name: str
    description: str = ""
    steps: list[WorkflowStep] = field(default_factory=list)
    vars: dict[str, Any] = field(default_factory=dict)

    def add_step(self, step: WorkflowStep) -> str:
        self.steps.append(step)
        return step.id


@dataclass
class WorkflowResult:
    step_id: str
    status: StepStatus
    output: str | None = None
    error: str | None = None


class WorkflowEngine:
    def __init__(self, default_config: AgentConfig | None = None):
        self.default_config = default_config or AgentConfig()
        self._results: dict[str, WorkflowResult] = {}
        self._vars: dict[str, Any] = {}

    async def run(self, workflow: Workflow) -> list[WorkflowResult]:
        self._vars = dict(workflow.vars)
        self._results = {}
        results: list[WorkflowResult] = []

        step_map = {s.id: s for s in workflow.steps}

        while True:
            ready = [
                s for s in workflow.steps
                if s.status == StepStatus.PENDING
                and all(
                    step_map.get(d, WorkflowStep(id="", name="")).status == StepStatus.COMPLETED
                    for d in s.depends_on
                )
            ]

            if not ready:
                if all(s.status in (StepStatus.COMPLETED, StepStatus.FAILED, StepStatus.SKIPPED)
                       for s in workflow.steps):
                    break
                failed = [s for s in workflow.steps if s.status == StepStatus.FAILED]
                if failed:
                    break
                await asyncio.sleep(0.1)
                continue

            for step in ready:
                if step.condition:
                    try:
                        if not eval(step.condition, {"__builtins__": {}}, self._vars):
                            step.status = StepStatus.SKIPPED
                            r = WorkflowResult(step.id, StepStatus.SKIPPED, output="Condition not met")
                            self._results[step.id] = r
                            results.append(r)
                            continue
                    except Exception as e:
                        step.status = StepStatus.FAILED
                        r = WorkflowResult(step.id, StepStatus.FAILED, error=f"Condition error: {e}")
                        self._results[step.id] = r
                        results.append(r)
                        continue

                r = await self._run_step(step)
                results.append(r)

        return results

    async def _run_step(self, step: WorkflowStep) -> WorkflowResult:
        step.status = StepStatus.RUNNING
        config = step.agent_config or self.default_config
        config.max_iterations = min(config.max_iterations, 20)

        for attempt in range(step.max_retries + 1):
            try:
                agent = Agent(config)
                output = await asyncio.wait_for(
                    agent.run(step.prompt), timeout=step.timeout
                )
                step.status = StepStatus.COMPLETED
                step.result = output
                self._vars[f"step.{step.id}.result"] = output
                r = WorkflowResult(step.id, StepStatus.COMPLETED, output=output)
                self._results[step.id] = r
                return r
            except asyncio.TimeoutError:
                error = f"Timed out after {step.timeout}s"
            except Exception as e:
                error = str(e)

            if attempt < step.max_retries:
                await asyncio.sleep(1)

        step.status = StepStatus.FAILED
        step.error = error
        r = WorkflowResult(step.id, StepStatus.FAILED, error=error)
        self._results[step.id] = r
        return r

    def get_result(self, step_id: str) -> WorkflowResult | None:
        return self._results.get(step_id)

    def get_vars(self) -> dict[str, Any]:
        return dict(self._vars)
