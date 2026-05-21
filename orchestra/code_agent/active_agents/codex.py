from __future__ import annotations

import asyncio
import os
import shutil
import time
from pathlib import Path
from typing import Any, Callable

from orchestra.code_agent.active_agents.base import (
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
        self._cli_path = cli_path or self._default_cli_path()
        self._model = model
        self._timeout = timeout
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")

    async def execute(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        event_callback: Callable | None = None,
    ) -> AgentResult:
        ctx = context or {}
        start = time.time()
        cwd = ctx.get("cwd")
        prompt = self._build_prompt(task, ctx)

        if event_callback is not None:
            await self._emit_event(
                event_callback,
                {
                    "type": "agent_init",
                    "data": {
                        "agent": self.name,
                        "display_name": self.display_name,
                        "model": self._model,
                        "engine": self.name,
                        "mode": "cli_or_api_fallback",
                    },
                },
            )

        # Try CLI first
        cli = self._resolve_cli()
        if cli:
            result = await self._run_cli(cli, prompt, cwd, start)
            if result.success:
                return result
            if not self._api_key:
                return result

        # Fall back to OpenAI API
        return await self._api_execute(prompt, start)

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
        except (FileNotFoundError, PermissionError, OSError, asyncio.TimeoutError) as e:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=str(e), duration_ms=(time.time() - start) * 1000,
            )

    async def _api_execute(self, prompt: str, start: float) -> AgentResult:
        if not self._api_key:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error="No OPENAI_API_KEY set and codex CLI not available",
                duration_ms=(time.time() - start) * 1000,
            )
        try:
            import httpx

            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/responses",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "input": prompt,
                        "reasoning": {"effort": "medium"},
                    },
                )

                if resp.status_code == 404 or resp.status_code == 400:
                    resp = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={
                            "model": "gpt-4o",
                            "messages": [
                                {
                                    "role": "system",
                                    "content": (
                                        "You are Codex, an expert coding assistant. "
                                        "Return working code. No placeholders. Be precise and complete."
                                    ),
                                },
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": 0.2,
                            "max_tokens": 4096,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    output = data["choices"][0]["message"]["content"]
                    meta = {"via": "chat_completions", "model": "gpt-4o"}
                else:
                    resp.raise_for_status()
                    data = resp.json()
                    output = self._extract_responses_output(data)
                    meta = {"via": "responses", "model": self._model}

            return AgentResult(
                agent_name=self.name,
                output=output,
                success=bool(output),
                duration_ms=(time.time() - start) * 1000,
                metadata=meta,
            )
        except Exception as e:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=str(e), duration_ms=(time.time() - start) * 1000,
            )

    async def health_check(self) -> AgentHealthStatus:
        start = time.time()
        cli = self._resolve_cli()
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
                    status=await self._cli_auth_status(cli),
                    version=stdout.decode().strip(),
                    latency_ms=(time.time() - start) * 1000,
                    detail=await self._cli_auth_detail(cli),
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

    @staticmethod
    def _default_cli_path() -> str:
        env_path = os.environ.get("ORCHESTRA_CODEX_CLI")
        if env_path:
            return env_path

        repo_root = Path(__file__).resolve().parents[3]
        local_cmd = repo_root / ".orchestra-tools" / "codex-cli" / "node_modules" / ".bin" / "codex.cmd"
        if local_cmd.exists():
            return str(local_cmd)

        return shutil.which("codex") or "codex"

    def _resolve_cli(self) -> str | None:
        candidate = Path(self._cli_path)
        if candidate.is_file():
            return str(candidate)
        return shutil.which(self._cli_path) or shutil.which("codex")

    async def _cli_auth_status(self, cli: str) -> AgentStatus:
        try:
            proc = await asyncio.create_subprocess_exec(
                cli, "login", "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=10)
            return AgentStatus.AVAILABLE if proc.returncode == 0 else AgentStatus.DEGRADED
        except Exception:
            return AgentStatus.AVAILABLE

    async def _cli_auth_detail(self, cli: str) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                cli, "login", "status",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            text = (stdout or stderr).decode("utf-8", errors="replace").strip()
            if proc.returncode == 0:
                return text or "CLI available and authenticated"
            return text or "CLI installed but not authenticated"
        except Exception:
            return "CLI available"

    def _build_prompt(self, task: str, context: dict[str, Any]) -> str:
        parts: list[str] = []
        cwd = context.get("cwd")
        if cwd:
            parts.append(f"Workspace: {cwd}")
        scaffold = context.get("append_system_prompt")
        if scaffold:
            parts.append(scaffold)
        files = context.get("files", {})
        if files:
            file_ctx = "\n\n".join(f"# {k}\n{v}" for k, v in list(files.items())[:3])
            parts.append(f"Context files:\n{file_ctx}")
        parts.append(f"Task: {task}")
        return "\n\n".join(p for p in parts if p)

    @staticmethod
    def _extract_responses_output(data: dict[str, Any]) -> str:
        output_parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    output_parts.append(text)
        if output_parts:
            return "\n".join(output_parts).strip()
        return data.get("output_text", "") or ""

    @staticmethod
    async def _emit_event(event_callback: Callable, event: dict[str, Any]) -> None:
        maybe_awaitable = event_callback(event)
        if asyncio.iscoroutine(maybe_awaitable):
            await maybe_awaitable
