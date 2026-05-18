from __future__ import annotations

import asyncio
import shutil
import time
from typing import Any

from code_agent.active_agents.base import (
    ActiveAgent, AgentCapability, AgentHealthStatus, AgentResult, AgentStatus,
)


class ClaudeCodeAgent(ActiveAgent):
    """Driver for Claude Code CLI agent.

    Spawns `claude -p "<task>"` as a subprocess and captures stdout.
    Falls back to Anthropic API if the CLI is unavailable.
    """

    name = "claude_code"
    display_name = "Claude Code"
    priority = 10
    capabilities = [
        AgentCapability(
            name="coding",
            description="Full-stack coding, refactoring, debugging, and code review",
            intent_keywords=["write", "code", "implement", "refactor", "debug", "fix", "class", "function", "bug"],
        ),
        AgentCapability(
            name="file_ops",
            description="Read, write, edit files and navigate codebases",
            intent_keywords=["read", "file", "edit", "write file", "create file", "delete"],
        ),
        AgentCapability(
            name="git",
            description="Git operations, commits, branches, PRs",
            intent_keywords=["git", "commit", "branch", "pr", "pull request", "merge"],
        ),
        AgentCapability(
            name="shell",
            description="Run shell commands, scripts, and build tools",
            intent_keywords=["run", "bash", "shell", "execute", "build", "test", "npm", "pip"],
        ),
    ]

    def __init__(
        self,
        cli_path: str | None = None,
        timeout: int = 120,
        max_turns: int = 10,
        allowed_tools: str = "all",
    ):
        self._cli_path = cli_path or shutil.which("claude") or "claude"
        self._timeout = timeout
        self._max_turns = max_turns
        self._allowed_tools = allowed_tools

    async def execute(
        self, task: str, context: dict[str, Any] | None = None
    ) -> AgentResult:
        ctx = context or {}
        start = time.time()
        cwd = ctx.get("cwd")

        cmd = [
            self._cli_path,
            "--print",
            "--output-format", "text",
            "--max-turns", str(self._max_turns),
            "-p", task,
        ]
        if self._allowed_tools != "all":
            cmd += ["--allowedTools", self._allowed_tools]

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
            duration = (time.time() - start) * 1000
            output = stdout.decode("utf-8", errors="replace").strip()
            err_text = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0 and output:
                return AgentResult(
                    agent_name=self.name,
                    output=output,
                    success=True,
                    duration_ms=duration,
                    metadata={"returncode": 0, "stderr_preview": err_text[:200]},
                )
            return AgentResult(
                agent_name=self.name,
                output=output or err_text,
                success=False,
                error=err_text or f"claude exited with code {proc.returncode}",
                duration_ms=duration,
                metadata={"returncode": proc.returncode},
            )
        except asyncio.TimeoutError:
            return AgentResult(
                agent_name=self.name,
                output="",
                success=False,
                error=f"Claude Code timed out after {self._timeout}s",
                duration_ms=(time.time() - start) * 1000,
            )
        except FileNotFoundError:
            return await self._api_fallback(task, start)
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                output="",
                success=False,
                error=str(e),
                duration_ms=(time.time() - start) * 1000,
            )

    async def _api_fallback(self, task: str, start: float) -> AgentResult:
        """Fall back to Anthropic API when CLI is unavailable."""
        try:
            import anthropic
            client = anthropic.AsyncAnthropic()
            msg = await client.messages.create(
                model="claude-opus-4-7-20251101",
                max_tokens=4096,
                messages=[{"role": "user", "content": task}],
            )
            output = msg.content[0].text if msg.content else ""
            return AgentResult(
                agent_name=self.name,
                output=output,
                success=bool(output),
                duration_ms=(time.time() - start) * 1000,
                metadata={"via": "api", "model": "claude-opus-4-7"},
            )
        except Exception as e:
            return AgentResult(
                agent_name=self.name,
                output="",
                success=False,
                error=f"CLI unavailable and API fallback failed: {e}",
                duration_ms=(time.time() - start) * 1000,
            )

    async def health_check(self) -> AgentHealthStatus:
        start = time.time()
        cli = shutil.which("claude") or self._cli_path
        if not cli or not shutil.which(cli.split()[0] if " " in (cli or "") else cli):
            # No CLI — check API availability
            try:
                import anthropic  # noqa: F401
                return AgentHealthStatus(
                    agent_name=self.name,
                    status=AgentStatus.DEGRADED,
                    detail="CLI unavailable; API fallback available",
                    latency_ms=(time.time() - start) * 1000,
                )
            except ImportError:
                return AgentHealthStatus(
                    agent_name=self.name,
                    status=AgentStatus.UNAVAILABLE,
                    detail="claude CLI not found and anthropic SDK not installed",
                )

        try:
            proc = await asyncio.create_subprocess_exec(
                cli, "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
            version = stdout.decode().strip().split("\n")[0]
            return AgentHealthStatus(
                agent_name=self.name,
                status=AgentStatus.AVAILABLE,
                version=version,
                latency_ms=(time.time() - start) * 1000,
                detail="CLI available",
            )
        except Exception as e:
            return AgentHealthStatus(
                agent_name=self.name,
                status=AgentStatus.UNAVAILABLE,
                detail=str(e),
                latency_ms=(time.time() - start) * 1000,
            )
