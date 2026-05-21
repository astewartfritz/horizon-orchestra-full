"""Sandbox lifecycle manager — creates, manages, and destroys Docker sandbox containers.

The agent decides what code or shell action to run.
Docker is where those actions are safely executed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from orchestra.code_agent.sandbox.policy import SandboxPolicy, ResourceLimits


@dataclass
class SandboxContainer:
    id: str
    image: str
    name: str = ""
    created_at: float = 0.0
    status: str = "created"
    workdir: str = "/workspace"
    host_workspace: str = ""


class SandboxManager:
    """Manages Docker sandbox lifecycle — start, exec, stop, cleanup.

    Each sandbox is an isolated Docker container with resource limits,
    restricted network access, and workspace mounting.
    """

    def __init__(self, policy: SandboxPolicy | None = None):
        self.policy = policy or SandboxPolicy()
        self._containers: dict[str, SandboxContainer] = {}
        self.logger = logging.getLogger("orchestra.sandbox")

    async def create(self, image: str = "python:3.11-slim",
                     name: str = "", workdir: str = "/workspace",
                     workspace_mount: str = "") -> SandboxContainer:
        """Create a new sandbox container."""
        import uuid
        cid = uuid.uuid4().hex[:12]
        container_name = name or f"orch-sandbox-{cid}"
        host_ws = workspace_mount or os.getcwd()

        # Build docker run args
        limits = self.policy.resource_limits
        cmd = [
            "docker", "run", "-d", "--rm",
            "--name", container_name,
            "--network", "none" if self.policy.network_isolated else "bridge",
            "-w", workdir,
            "-v", f"{host_ws}:{workdir}",
            "--memory", limits.memory,
            "--cpus", str(limits.cpu_count),
            "--pids-limit", str(limits.pids_limit),
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true",
            "--read-only" if limits.readonly_root else "",
            image,
            "tail", "-f", "/dev/null",  # Keep container running
        ]
        cmd = [c for c in cmd if c]  # Remove empty strings

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
            if proc.returncode != 0:
                err = stderr.decode() if stderr else "Unknown error"
                raise RuntimeError(f"Docker create failed: {err}")

            container_id = stdout.decode().strip()
            container = SandboxContainer(
                id=container_id,
                image=image,
                name=container_name,
                created_at=time.time(),
                workdir=workdir,
                host_workspace=host_ws,
            )
            self._containers[container_id] = container
            self.logger.info("Sandbox created: %s (%s)", container_name, image)
            return container

        except FileNotFoundError:
            raise RuntimeError("Docker is not installed or not in PATH")

    async def exec(self, container_id: str, command: str,
                   timeout: int = 60) -> tuple[str, str, int]:
        """Execute a command inside a running sandbox container."""
        container = self._containers.get(container_id)
        if not container:
            raise ValueError(f"Container not found: {container_id}")

        cmd = ["docker", "exec", container_id, "sh", "-c", command]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            out = stdout.decode("utf-8", errors="replace") if stdout else ""
            err = stderr.decode("utf-8", errors="replace") if stderr else ""
            return out, err, proc.returncode or 0
        except asyncio.TimeoutError:
            proc.kill()
            raise TimeoutError(f"Command timed out after {timeout}s")

    async def exec_python(self, container_id: str, code: str) -> str:
        """Execute Python code inside the sandbox."""
        out, err, rc = await self.exec(container_id, f'python3 -c "{code}"')
        if rc != 0:
            return f"Error (exit {rc}): {err[:1000] if err else out[:1000]}"
        return out[:50000] if out else "(no output)"

    async def exec_node(self, container_id: str, code: str) -> str:
        """Execute Node.js code inside the sandbox."""
        out, err, rc = await self.exec(container_id, f'node -e "{code}"')
        if rc != 0:
            return f"Error (exit {rc}): {err[:1000] if err else out[:1000]}"
        return out[:50000] if out else "(no output)"

    async def write_file(self, container_id: str, path: str, content: str) -> None:
        """Write a file inside the sandbox."""
        escaped = content.replace("'", "'\\''")
        await self.exec(container_id, f"mkdir -p $(dirname '{path}') && echo '{escaped}' > '{path}'")

    async def read_file(self, container_id: str, path: str) -> str:
        """Read a file from inside the sandbox."""
        out, err, rc = await self.exec(container_id, f"cat '{path}'")
        if rc != 0:
            return f"Error: {err[:500]}" if err else "File not found"
        return out

    async def install_package(self, container_id: str, package: str) -> str:
        """Install a Python package inside the sandbox."""
        out, err, rc = await self.exec(container_id, f"pip install {package}", timeout=120)
        if rc != 0:
            return f"Install error: {err[:500]}"
        return f"Installed {package}"

    async def stop(self, container_id: str) -> None:
        """Stop and remove a sandbox container."""
        container = self._containers.get(container_id)
        if not container:
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "stop", container_id,
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)
        except Exception:
            pass
        finally:
            self._containers.pop(container_id, None)
            self.logger.info("Sandbox stopped: %s", container.name)

    async def stop_all(self) -> None:
        """Stop all running sandbox containers."""
        for cid in list(self._containers.keys()):
            await self.stop(cid)

    def list(self) -> list[dict[str, Any]]:
        return [{
            "id": c.id[:12],
            "name": c.name,
            "image": c.image,
            "status": c.status,
            "age_s": int(time.time() - c.created_at) if c.created_at else 0,
        } for c in self._containers.values()]
