from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from code_agent.tools.base import Tool, ToolResult, ToolSpec


class DockerSandbox(Tool):
    spec = ToolSpec(
        name="sandbox",
        description="Execute a command inside a Docker container sandbox. Useful for running untrusted code safely.",
        parameters={
            "command": {"type": "string", "description": "Command to run inside the container"},
            "image": {"type": "string", "description": "Docker image to use", "default": "python:3.11-slim"},
            "workdir": {"type": "string", "description": "Working directory inside container", "default": "/workspace"},
            "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 60},
            "volumes": {
                "type": "string",
                "description": "Additional volume mounts as JSON string: {\"/host\": \"/container\"}",
                "default": "",
            },
        },
    )

    async def __call__(
        self,
        command: str,
        image: str = "python:3.11-slim",
        workdir: str = "/workspace",
        timeout: int = 60,
        volumes: str = "",
    ) -> ToolResult:
        try:
            vol_args = []
            if volumes:
                import json
                vols = json.loads(volumes)
                for host_path, container_path in vols.items():
                    vol_args.extend(["-v", f"{host_path}:{container_path}"])

            cmd = [
                "docker", "run", "--rm",
                "-w", workdir,
                *vol_args,
                image,
                "sh", "-c", command,
            ]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                return ToolResult(error=f"Sandbox command timed out after {timeout}s")

            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0 and err:
                return ToolResult(output=out, error=err[:5000])

            return ToolResult(output=out[:50000] if out else "(no output)")

        except FileNotFoundError:
            return ToolResult(error="Docker is not installed or not in PATH")
        except Exception as e:
            return ToolResult(error=str(e))
