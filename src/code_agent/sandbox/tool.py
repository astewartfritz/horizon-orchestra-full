"""Sandbox tool for the agent — runs code in isolated Docker containers.

The agent decides what code or shell action to run.
Docker is where those actions are safely executed.
"""

from __future__ import annotations

import os
from typing import Any

from code_agent.tools.base import Tool, ToolResult, ToolSpec
from code_agent.sandbox.manager import SandboxManager
from code_agent.sandbox.policy import SandboxPolicy


class SandboxExecuteTool(Tool):
    """Run code in an isolated Docker sandbox. Supports Python, Node, shell, and custom commands."""

    spec = ToolSpec(
        name="sandbox_exec",
        description="Execute code in a secure Docker sandbox. Supports Python, Node.js, shell. Files written persist for the session.",
        parameters={
            "language": {
                "type": "string",
                "enum": ["python", "node", "shell", "rust", "go"],
                "description": "Language to execute",
            },
            "code": {"type": "string", "description": "Code to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
        },
    )

    def __init__(self):
        self._manager: SandboxManager | None = None
        self._container_id: str | None = None
        self._policy = SandboxPolicy()

    async def _ensure_sandbox(self) -> str:
        if self._container_id:
            return self._container_id
        self._manager = SandboxManager(policy=self._policy)
        container = await self._manager.create(
            image=self._policy.get_image_for("python"),
            workspace_mount=os.getcwd(),
        )
        self._container_id = container.id
        return container.id

    async def __call__(self, language: str = "python", code: str = "",
                       timeout: int = 60) -> ToolResult:
        if not code:
            return ToolResult(error="No code provided")

        try:
            cid = await self._ensure_sandbox()

            if language == "python":
                # Write code to file and execute
                import uuid
                filename = f"/workspace/script_{uuid.uuid4().hex[:8]}.py"
                await self._manager.write_file(cid, filename, code)
                out, err, rc = await self._manager.exec(cid, f"python3 {filename}", timeout=timeout)

            elif language == "node":
                import uuid
                filename = f"/workspace/script_{uuid.uuid4().hex[:8]}.js"
                await self._manager.write_file(cid, filename, code)
                out, err, rc = await self._manager.exec(cid, f"node {filename}", timeout=timeout)

            elif language == "shell":
                out, err, rc = await self._manager.exec(cid, code, timeout=timeout)

            elif language in ("rust", "go"):
                return ToolResult(output=f"Language '{language}' sandbox requires a custom image. Use 'shell' with the compiler command instead.")

            else:
                return ToolResult(error=f"Unsupported language: {language}")

            output = out[:50000] if out else ""
            error = err[:5000] if err else ""

            if rc != 0 and error:
                return ToolResult(output=output, error=error)
            return ToolResult(output=output or "(no output)")

        except TimeoutError as e:
            return ToolResult(error=str(e))
        except RuntimeError as e:
            return ToolResult(error=f"Sandbox error: {e}")
        except Exception as e:
            return ToolResult(error=str(e))
