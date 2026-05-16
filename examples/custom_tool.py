"""Example: Create a custom tool and register it with the agent."""
import asyncio
import os
from datetime import datetime

from code_agent import Agent, AgentConfig, Tool, ToolResult, ToolSpec
from code_agent.config import LLMConfig


class TimestampTool(Tool):
    spec = ToolSpec(
        name="timestamp",
        description="Get the current date and time",
        parameters={"format": {
            "type": "string",
            "description": "Date format: iso, unix, or readable",
            "default": "iso",
        }},
    )

    async def __call__(self, format: str = "iso") -> ToolResult:
        now = datetime.now()
        if format == "unix":
            return ToolResult(output=str(int(now.timestamp())))
        elif format == "readable":
            return ToolResult(output=now.strftime("%A, %B %d, %Y at %I:%M %p"))
        else:
            return ToolResult(output=now.isoformat())


async def main():
    cfg = AgentConfig(
        llm=LLMConfig(
            provider="openai",
            model="gpt-4o",
            api_key=os.environ.get("OPENAI_API_KEY"),
        ),
        workspace=".",
        memory_type="none",
    )

    agent = Agent(cfg, custom_tools=[TimestampTool()])
    result = await agent.run("What is the current date and time? Use the timestamp tool.")
    print(result)


if __name__ == "__main__":
    asyncio.run(main())
