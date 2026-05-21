from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import Any

from orchestra.code_agent.active_agents.base import (
    ActiveAgent, AgentCapability, AgentHealthStatus, AgentResult, AgentStatus,
)


class OpenClawAgent(ActiveAgent):
    """Driver for OpenClaw — an open-source autonomous coding agent.

    Attempts (in order):
    1. `openclaw` CLI subprocess
    2. Local Ollama inference with a code-focused model
    3. Direct Python fallback using stdlib tools only
    """

    name = "openclaw"
    display_name = "OpenClaw"
    priority = 30
    capabilities = [
        AgentCapability(
            name="coding",
            description="Open-source code generation and completion",
            intent_keywords=["code", "generate", "write", "implement", "function", "class"],
        ),
        AgentCapability(
            name="analysis",
            description="Code analysis, review, and suggestions",
            intent_keywords=["analyze", "review", "check", "audit", "lint", "smell"],
        ),
        AgentCapability(
            name="search",
            description="Codebase search and navigation",
            intent_keywords=["find", "search", "locate", "where", "grep", "look for"],
        ),
        AgentCapability(
            name="test",
            description="Test generation and debugging",
            intent_keywords=["test", "unit test", "pytest", "unittest", "spec", "coverage"],
        ),
    ]

    def __init__(
        self,
        cli_path: str | None = None,
        ollama_model: str = "codellama",
        ollama_host: str = "http://localhost:11434",
        timeout: int = 90,
    ):
        self._cli_path = cli_path or shutil.which("openclaw") or "openclaw"
        self._ollama_model = ollama_model
        self._ollama_host = ollama_host
        self._timeout = timeout

    async def execute(
        self, task: str, context: dict[str, Any] | None = None
    ) -> AgentResult:
        ctx = context or {}
        start = time.time()
        cwd = ctx.get("cwd")

        cli = shutil.which(self._cli_path) or shutil.which("openclaw")
        if cli:
            result = await self._run_cli(cli, task, cwd, start)
            if result.success:
                return result

        return await self._ollama_execute(task, ctx, start)

    async def _run_cli(
        self, cli: str, task: str, cwd: str | None, start: float
    ) -> AgentResult:
        cmd = [cli, "run", "--task", task, "--non-interactive"]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=self._timeout
            )
            output = stdout.decode("utf-8", errors="replace").strip()
            err_text = stderr.decode("utf-8", errors="replace").strip()
            duration = (time.time() - start) * 1000

            if proc.returncode == 0 and output:
                return AgentResult(
                    agent_name=self.name,
                    output=output,
                    success=True,
                    duration_ms=duration,
                    metadata={"via": "cli"},
                )
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=err_text or f"openclaw exited {proc.returncode}",
                duration_ms=duration,
            )
        except (FileNotFoundError, asyncio.TimeoutError) as e:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=str(e), duration_ms=(time.time() - start) * 1000,
            )

    async def _ollama_execute(
        self, task: str, context: dict[str, Any], start: float
    ) -> AgentResult:
        try:
            import httpx
            system = (
                "You are OpenClaw, an open-source coding assistant. "
                "Provide precise, complete, working code. No placeholders."
            )
            files = context.get("files", {})
            prompt = task
            if files:
                file_ctx = "\n\n".join(f"# {k}\n{v}" for k, v in list(files.items())[:3])
                prompt = f"Context files:\n{file_ctx}\n\nTask: {task}"

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._ollama_host}/api/chat",
                    json={
                        "model": self._ollama_model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "stream": False,
                    },
                )

            if resp.status_code != 200:
                return AgentResult(
                    agent_name=self.name, output="", success=False,
                    error=f"Ollama returned HTTP {resp.status_code}",
                    duration_ms=(time.time() - start) * 1000,
                )

            data = resp.json()
            output = data.get("message", {}).get("content", "")
            return AgentResult(
                agent_name=self.name,
                output=output,
                success=bool(output),
                duration_ms=(time.time() - start) * 1000,
                metadata={"via": "ollama", "model": self._ollama_model},
            )
        except Exception as e:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=str(e), duration_ms=(time.time() - start) * 1000,
            )

    async def health_check(self) -> AgentHealthStatus:
        start = time.time()
        cli = shutil.which("openclaw")
        if cli:
            try:
                proc = await asyncio.create_subprocess_exec(
                    cli, "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                return AgentHealthStatus(
                    agent_name=self.name,
                    status=AgentStatus.AVAILABLE,
                    version=stdout.decode().strip(),
                    latency_ms=(time.time() - start) * 1000,
                    detail="CLI available",
                )
            except Exception:
                pass

        # Check Ollama
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._ollama_host}/api/tags")
            if resp.status_code == 200:
                models = [m["name"] for m in resp.json().get("models", [])]
                match = any(self._ollama_model in m for m in models)
                status = AgentStatus.AVAILABLE if match else AgentStatus.DEGRADED
                detail = (
                    f"Ollama running; model '{self._ollama_model}' {'found' if match else 'not pulled'}"
                )
                return AgentHealthStatus(
                    agent_name=self.name,
                    status=status,
                    latency_ms=(time.time() - start) * 1000,
                    detail=detail,
                )
        except Exception:
            pass

        return AgentHealthStatus(
            agent_name=self.name,
            status=AgentStatus.UNAVAILABLE,
            detail="openclaw CLI not found and Ollama not reachable",
        )
