from __future__ import annotations

import asyncio
import os
import shutil
import time
from typing import Any

from code_agent.active_agents.base import (
    ActiveAgent, AgentCapability, AgentHealthStatus, AgentResult, AgentStatus,
)


class CodexAgent(ActiveAgent):
    """Driver for OpenAI Codex agent.

    Attempts (in order):
    1. `codex` CLI subprocess (OpenAI Codex CLI if installed)
    2. OpenAI Responses API with `codex-mini-latest`
    3. OpenAI Chat Completions with a code-focused system prompt
    """

    name = "codex"
    display_name = "Codex"
    priority = 20
    capabilities = [
        AgentCapability(
            name="coding",
            description="Code generation, completion, and transformation",
            intent_keywords=["code", "implement", "write function", "algorithm", "generate", "complete"],
        ),
        AgentCapability(
            name="refactor",
            description="Refactoring and code quality improvements",
            intent_keywords=["refactor", "clean up", "improve", "optimize", "rewrite"],
        ),
        AgentCapability(
            name="explain",
            description="Code explanation and documentation",
            intent_keywords=["explain", "document", "what does", "how does", "describe"],
        ),
    ]

    def __init__(
        self,
        cli_path: str | None = None,
        model: str = "codex-mini-latest",
        timeout: int = 90,
        api_key: str | None = None,
    ):
        self._cli_path = cli_path or shutil.which("codex") or "codex"
        self._model = model
        self._timeout = timeout
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    async def execute(
        self, task: str, context: dict[str, Any] | None = None
    ) -> AgentResult:
        ctx = context or {}
        start = time.time()
        cwd = ctx.get("cwd")

        # Try CLI first
        cli = shutil.which(self._cli_path) or shutil.which("codex")
        if cli:
            result = await self._run_cli(cli, task, cwd, start)
            if result.success:
                return result

        # Fall back to OpenAI API
        return await self._api_execute(task, ctx, start)

    async def _run_cli(
        self, cli: str, task: str, cwd: str | None, start: float
    ) -> AgentResult:
        cmd = [cli, "--full-auto", "-q", task]
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
                error=err_text or f"codex exited {proc.returncode}",
                duration_ms=duration,
            )
        except (FileNotFoundError, asyncio.TimeoutError) as e:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=str(e), duration_ms=(time.time() - start) * 1000,
            )

    async def _api_execute(
        self, task: str, context: dict[str, Any], start: float
    ) -> AgentResult:
        if not self._api_key:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error="No OPENAI_API_KEY set and codex CLI not available",
                duration_ms=(time.time() - start) * 1000,
            )
        try:
            import httpx
            system = (
                "You are Codex, an expert coding assistant. "
                "Return working code. No placeholders. Be precise and complete."
            )
            files = context.get("files", {})
            prompt = task
            if files:
                file_ctx = "\n\n".join(f"# {k}\n{v}" for k, v in list(files.items())[:3])
                prompt = f"Context files:\n{file_ctx}\n\nTask: {task}"

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    json={
                        "model": "gpt-4o",
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 4096,
                    },
                )
            data = resp.json()
            output = data["choices"][0]["message"]["content"]
            return AgentResult(
                agent_name=self.name,
                output=output,
                success=bool(output),
                duration_ms=(time.time() - start) * 1000,
                metadata={"via": "api", "model": "gpt-4o"},
            )
        except Exception as e:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=str(e), duration_ms=(time.time() - start) * 1000,
            )

    async def health_check(self) -> AgentHealthStatus:
        start = time.time()
        cli = shutil.which("codex")
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

        # Check API key
        if self._api_key:
            return AgentHealthStatus(
                agent_name=self.name,
                status=AgentStatus.DEGRADED,
                latency_ms=(time.time() - start) * 1000,
                detail="CLI unavailable; OpenAI API key available",
            )
        return AgentHealthStatus(
            agent_name=self.name,
            status=AgentStatus.UNAVAILABLE,
            detail="codex CLI not found and OPENAI_API_KEY not set",
        )
