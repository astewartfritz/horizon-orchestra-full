from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable

from orchestra.code_agent.agent import Agent
from orchestra.code_agent.config import AgentConfig


@dataclass
class PipelineStep:
    name: str = ""
    task: str = ""
    profile: str = ""
    agent_config: AgentConfig | None = None
    transform: Callable[[str], str] | None = None
    depends_on: list[str] = field(default_factory=list)


@dataclass
class PipelineStepResult:
    step_name: str
    output: str = ""
    error: str = ""
    duration_ms: float = 0.0


class PipelineEngine:
    """Chain multiple agents in a pipeline, passing outputs between steps."""

    def __init__(self, steps: list[PipelineStep] | None = None):
        self.steps = steps or []

    def add_step(self, step: PipelineStep) -> None:
        self.steps.append(step)

    async def run(self, initial_input: str = "") -> list[PipelineStepResult]:
        results: list[PipelineStepResult] = []
        context: dict[str, str] = {"_input": initial_input}

        for step in self.steps:
            from orchestra.code_agent.profiles.base import load_profile
            cfg = step.agent_config
            if not cfg and step.profile:
                cfg = load_profile(step.profile)
            if not cfg:
                cfg = AgentConfig(name=step.name)

            agent = Agent(cfg)
            task = step.task

            # Inject context from previous steps
            for key, val in context.items():
                placeholder = f"{{{{{key}}}}}"
                if placeholder in task:
                    task = task.replace(placeholder, val)

            if step.transform:
                task = step.transform(task)

            start = asyncio.get_event_loop().time()

            try:
                output = await agent.run(task)
                duration = (asyncio.get_event_loop().time() - start) * 1000
                results.append(PipelineStepResult(step_name=step.name, output=output, duration_ms=duration))
                context[step.name] = output
            except Exception as e:
                duration = (asyncio.get_event_loop().time() - start) * 1000
                results.append(PipelineStepResult(step_name=step.name, error=str(e), duration_ms=duration))

        return results
