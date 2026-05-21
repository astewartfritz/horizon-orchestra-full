from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestra.code_agent.agent import Agent
from orchestra.code_agent.config import AgentConfig


@dataclass
class ReflectionResult:
    initial_answer: str = ""
    self_critique: str = ""
    improved_answer: str = ""
    final_answer: str = ""


class ReflectiveAgent:
    """Agent that reflects on and improves its own outputs."""

    def __init__(self, config: AgentConfig | None = None):
        self.agent = Agent(config or AgentConfig(name="Reflector"))

    async def solve(self, task: str, reflection_steps: int = 2) -> ReflectionResult:
        result = ReflectionResult()

        result.initial_answer = await self.agent.run(
            f"Solve this task:\n\n{task}\n\nProvide your best solution."
        )

        current = result.initial_answer
        for step in range(reflection_steps):
            critique = await self.agent.run(
                f"Original task: {task}\n\n"
                f"Current solution:\n{current}\n\n"
                f"Critique this solution thoroughly. Find errors, omissions, "
                f"and areas for improvement. Be specific."
            )
            if step == 0:
                result.self_critique = critique

            improved = await self.agent.run(
                f"Original task: {task}\n\n"
                f"Previous solution:\n{current}\n\n"
                f"Critique received:\n{critique}\n\n"
                f"Provide an improved solution that addresses all critique points."
            )
            current = improved

        result.improved_answer = current

        result.final_answer = await self.agent.run(
            f"Original task: {task}\n\n"
            f"Final solution:\n{current}\n\n"
            f"Summarize the final answer concisely."
        )

        return result


async def reflect_tool(**kwargs: Any) -> str:
    """Self-reflection tool: agent critiques and improves its own answer."""
    task = kwargs.get("task", "")
    if not task:
        return "Error: task required"

    reflector = ReflectiveAgent()
    result = await reflector.solve(task)
    return (
        f"## Initial Answer\n{result.initial_answer[:500]}\n\n"
        f"## Self-Critique\n{result.self_critique[:500]}\n\n"
        f"## Improved Answer\n{result.improved_answer[:500]}\n\n"
        f"## Final Answer\n{result.final_answer[:500]}"
    )
