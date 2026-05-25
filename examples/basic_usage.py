"""Basic example: Run the code agent with a simple task.

Usage:
    export OPENAI_API_KEY=sk-...
    python examples/basic_usage.py
"""
import asyncio
import os

from orchestra.code_agent import Agent, AgentConfig
from orchestra.code_agent.config import LLMConfig


async def main():
    cfg = AgentConfig(
        llm=LLMConfig(
            provider="openai",
            model="gpt-4o",
            api_key=os.environ.get("OPENAI_API_KEY"),
        ),
        workspace=".",
        memory_type="none",
        max_iterations=30,
    )

    agent = Agent(cfg)

    result = await agent.run("List all Python files in the current directory and count their total lines")

    print("Result:")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
