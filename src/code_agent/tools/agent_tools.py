from __future__ import annotations

from code_agent.tools.base import Tool, ToolResult, ToolSpec


class TaskTool(Tool):
    spec = ToolSpec(
        name="task",
        description="Delegate a complex subtask to a sub-agent. Use for multi-step research or implementation work.",
        parameters={
            "description": {"type": "string", "description": "Short description of the subtask (3-5 words)"},
            "prompt": {"type": "string", "description": "Detailed instructions for the sub-agent"},
        },
    )

    async def __call__(self, description: str, prompt: str) -> ToolResult:
        return ToolResult(
            output=f"[Sub-agent '{description}' delegated]\n"
                   f"Prompt: {prompt[:200]}...\n"
                   f"(Sub-agent execution requires a parent agent loop to handle)"
        )
