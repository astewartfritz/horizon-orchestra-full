from __future__ import annotations

import asyncio
import subprocess
import sys

from code_agent.tools.base import Tool, ToolResult, ToolSpec


class BashTool(Tool):
    spec = ToolSpec(
        name="bash",
        description="Execute a shell command. Returns stdout/stderr. Timeout applies after the given duration.",
        parameters={
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout": {"type": "integer", "description": "Timeout in milliseconds (default 120000)", "default": 120000},
            "description": {"type": "string", "description": "Brief description of what this command does"},
            "workdir": {"type": "string", "description": "Working directory for the command"},
        },
    )

    POWERSHELL_PREFIX = (
        "$ErrorActionPreference='Stop'; "
        "$PSDefaultParameterValues['*:Encoding'] = 'utf8'; "
    )

    async def __call__(
        self,
        command: str,
        timeout: int = 120000,
        description: str | None = None,
        workdir: str | None = None,
    ) -> ToolResult:
        try:
            shell_cmd = f'powershell -NoProfile -Command "{self.POWERSHELL_PREFIX}{command}"'

            proc = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workdir,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout / 1000
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(error=f"Command timed out after {timeout}ms")

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0 and err:
                return ToolResult(output=out, error=err[:5000])

            return ToolResult(output=out[:50000] if out else "(completed with no output)")
        except Exception as e:
            return ToolResult(error=str(e))
