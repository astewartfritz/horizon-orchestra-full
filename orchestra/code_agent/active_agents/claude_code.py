from __future__ import annotations

import asyncio
import json
import shutil
import time
from typing import Any, Callable

from orchestra.code_agent.active_agents.base import (
    ActiveAgent, AgentCapability, AgentHealthStatus, AgentResult, AgentStatus,
)


def _tool_action_type(name: str) -> str:
    _MAP = {
        "Read": "read", "Write": "edit", "Edit": "edit", "MultiEdit": "edit",
        "Glob": "search", "Grep": "search",
        "Bash": "command", "PowerShell": "command",
        "WebFetch": "web", "WebSearch": "web",
        "Git": "git",
        "Task": "agent", "TaskCreate": "agent",
        "NotebookEdit": "edit", "NotebookRead": "read",
    }
    return _MAP.get(name, "tool")


def _extract_content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if not isinstance(c, dict):
                continue
            t = c.get("type", "")
            if t == "text":
                parts.append(c.get("text", ""))
            elif t == "image":
                parts.append("[image]")
        return "\n".join(p for p in parts if p)
    return str(content) if content else ""


class ClaudeCodeAgent(ActiveAgent):
    """Driver for the Claude Code CLI.

    Streaming mode (when event_callback is provided) uses
    --output-format stream-json --verbose --include-partial-messages to emit
    real-time events — tool calls, text tokens, cost — as Claude works.

    Non-streaming mode (no callback) is the original text-format path,
    kept for backward compatibility and health checks.
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
        timeout: int = 3600,       # 1 hour — no artificial cap
        max_turns: int = 0,        # 0 = no --max-turns flag (unlimited)
        allowed_tools: str = "all",
    ):
        self._cli_path = cli_path or shutil.which("claude") or "claude"
        self._timeout = timeout
        self._max_turns = max_turns
        self._allowed_tools = allowed_tools

    # ── Public entry point ────────────────────────────────────────────────────

    async def execute(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        event_callback: Callable | None = None,
    ) -> AgentResult:
        ctx = context or {}
        start = time.time()
        cwd = ctx.get("cwd") or None
        session_id = ctx.get("claude_session_id")

        if event_callback is not None:
            return await self._stream(task, ctx, cwd, session_id, start, event_callback)
        return await self._simple(task, cwd, start)

    # ── Streaming path ────────────────────────────────────────────────────────

    def _build_cmd(
        self,
        task: str,
        ctx: dict,
        session_id: str | None,
        streaming: bool,
    ) -> list[str]:
        effort = ctx.get("effort", "high")
        model = ctx.get("model") or None
        extra_dirs: list[str] = ctx.get("additional_dirs", [])
        permission_mode = ctx.get("permission_mode", "bypassPermissions")
        append_prompt = ctx.get("append_system_prompt", "")

        cmd: list[str] = [
            self._cli_path,
            "--print",
            "--permission-mode", permission_mode,
            "--effort", effort,
        ]
        if self._max_turns > 0:
            cmd += ["--max-turns", str(self._max_turns)]
        if streaming:
            # stream-json + verbose gives us structured events.
            # --include-partial-messages gives us token-level text deltas via
            # stream_event/content_block_delta so text streams in real-time.
            cmd += [
                "--output-format", "stream-json",
                "--verbose",
                "--include-partial-messages",
            ]
        else:
            cmd += ["--output-format", "text"]

        if model:
            cmd += ["--model", model]
        if session_id:
            # --resume continues an existing conversation; --fork-session
            # creates a new session ID each turn so we never hit "already in use".
            cmd += ["--resume", session_id, "--fork-session"]
        for d in extra_dirs:
            cmd += ["--add-dir", str(d)]
        if append_prompt:
            # Newlines break Windows CreateProcess argument parsing —
            # compress to semicolons so the scaffold stays readable.
            safe_prompt = " ".join(
                line.strip() for line in append_prompt.splitlines() if line.strip()
            )
            cmd += ["--append-system-prompt", safe_prompt]
        if self._allowed_tools != "all":
            cmd += ["--allowedTools", self._allowed_tools]

        cmd += ["-p", task]
        return cmd

    async def _stream(
        self,
        task: str,
        ctx: dict,
        cwd: str | None,
        session_id: str | None,
        start: float,
        enqueue: Callable,
    ) -> AgentResult:
        cmd = self._build_cmd(task, ctx, session_id, streaming=True)
        proc: asyncio.subprocess.Process | None = None

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            result_data: dict | None = None
            seen_session_id: str | None = None

            # Per-message state for incremental text/thinking streaming
            current_msg_id: str | None = None
            current_text: str = ""
            emitted_tool_ids: set[str] = set()
            # Maps msg_id_thinking → last emitted thinking text (for progressive updates)
            current_thinking_texts: dict[str, str] = {}

            async def read_lines() -> None:
                nonlocal result_data, seen_session_id, current_msg_id, current_text, current_thinking_texts

                assert proc is not None
                while True:
                    raw = await proc.stdout.readline()
                    if not raw:
                        break
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    ev_type: str = ev.get("type", "")

                    # ── Session init ──────────────────────────────────────────
                    if ev_type == "system" and ev.get("subtype") == "init":
                        seen_session_id = ev.get("session_id")
                        await enqueue({
                            "type": "agent_init",
                            "data": {
                                "session_id": seen_session_id,
                                "model": ev.get("model"),
                                "permission_mode": ev.get("permissionMode"),
                                "tools_count": len(ev.get("tools", [])),
                                "mcp_servers": [
                                    s["name"] for s in ev.get("mcp_servers", [])
                                    if s.get("status") not in ("needs-auth", "error")
                                ],
                            },
                        })

                    # ── Assistant turn ────────────────────────────────────────
                    # --include-partial-messages causes repeated assistant events
                    # with growing content. We emit deltas from the text blocks
                    # and use emitted_tool_ids to deduplicate tool_use blocks.
                    # stop_reason is always null in Claude Code stream-json so
                    # we cannot use it for partial-vs-final detection.
                    elif ev_type == "assistant":
                        msg = ev.get("message", {})
                        msg_id: str | None = msg.get("id")

                        if msg_id != current_msg_id:
                            current_msg_id = msg_id
                            current_text = ""

                        for block in msg.get("content", []):
                            btype: str = block.get("type", "")

                            if btype == "text":
                                full_text: str = block.get("text", "")
                                if full_text.startswith(current_text):
                                    delta = full_text[len(current_text):]
                                else:
                                    delta = full_text
                                if delta:
                                    await enqueue({"type": "token", "data": delta})
                                current_text = full_text

                            elif btype == "thinking":
                                thinking: str = block.get("thinking", "")
                                thinking_key = f"{msg_id}_thinking"
                                # Emit whenever the thinking content grows (partial-messages path)
                                if thinking and thinking != current_thinking_texts.get(thinking_key, ""):
                                    current_thinking_texts[thinking_key] = thinking
                                    await enqueue({"type": "thinking", "data": thinking[:4000]})

                            elif btype == "tool_use":
                                tool_id: str = block.get("id", "")
                                if tool_id in emitted_tool_ids:
                                    continue
                                emitted_tool_ids.add(tool_id)
                                tool_name: str = block.get("name", "unknown")
                                tool_input: dict = block.get("input", {})
                                await enqueue({
                                    "type": "tool_call",
                                    "data": {
                                        "name": tool_name,
                                        "arguments": tool_input,
                                        "tool_id": tool_id,
                                        "action_type": _tool_action_type(tool_name),
                                    },
                                })

                    # ── Tool results ──────────────────────────────────────────
                    elif ev_type == "user":
                        for block in ev.get("message", {}).get("content", []):
                            if block.get("type") != "tool_result":
                                continue
                            tool_id = block.get("tool_use_id", "")
                            is_error: bool = bool(block.get("is_error"))
                            raw_content = block.get("content", [])
                            text = _extract_content_text(raw_content)
                            await enqueue({
                                "type": "tool_result",
                                "data": {
                                    "output": text[:16000] if not is_error else "",
                                    "error": text[:500] if is_error else "",
                                    "tool_id": tool_id,
                                },
                            })

                    # ── Final result ──────────────────────────────────────────
                    elif ev_type == "result":
                        success: bool = ev.get("subtype") == "success" and not ev.get("is_error")
                        result_data = {
                            "result": ev.get("result", ""),
                            "cost": ev.get("total_cost_usd"),
                            "turns": ev.get("num_turns", 1),
                            "duration_ms": ev.get("duration_ms"),
                            "success": success,
                            "session_id": ev.get("session_id") or seen_session_id,
                            "error": ev.get("error") if not success else None,
                        }

            await asyncio.wait_for(read_lines(), timeout=self._timeout)
            await proc.wait()
            duration = (time.time() - start) * 1000

            if result_data:
                # result field can be empty when Claude Code edits files without a closing
                # text response — fall back to the last streamed assistant text in that case
                output = result_data["result"] or current_text
                return AgentResult(
                    agent_name=self.name,
                    output=output,
                    success=result_data["success"],
                    error=result_data.get("error") or ("" if result_data["success"] else "No output"),
                    duration_ms=duration,
                    metadata={
                        "cost_usd": result_data.get("cost"),
                        "turns": result_data.get("turns"),
                        "claude_session_id": result_data.get("session_id"),
                        "streaming": True,
                    },
                )

            # Drain stderr for a useful error message if no result event arrived
            stderr_bytes = await proc.stderr.read()
            err_msg = stderr_bytes.decode("utf-8", errors="replace").strip()[:400] if stderr_bytes else ""
            return AgentResult(
                agent_name=self.name,
                output="",
                success=False,
                error=err_msg or "Stream ended without a result event",
                duration_ms=duration,
            )

        except asyncio.TimeoutError:
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            return AgentResult(
                agent_name=self.name,
                output="",
                success=False,
                error=f"Claude Code timed out after {self._timeout}s",
                duration_ms=(time.time() - start) * 1000,
            )
        except FileNotFoundError:
            return await self._api_fallback(task, start)
        except Exception as exc:
            return AgentResult(
                agent_name=self.name,
                output="",
                success=False,
                error=str(exc),
                duration_ms=(time.time() - start) * 1000,
            )

    # ── Non-streaming fallback ────────────────────────────────────────────────

    async def _simple(self, task: str, cwd: str | None, start: float) -> AgentResult:
        cmd = [
            self._cli_path, "--print",
            "--output-format", "text",
            "--permission-mode", "bypassPermissions",
        ]
        if self._max_turns > 0:
            cmd += ["--max-turns", str(self._max_turns)]
        cmd += ["-p", task]
        if self._allowed_tools != "all":
            cmd += ["--allowedTools", self._allowed_tools]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            duration = (time.time() - start) * 1000
            output = stdout.decode("utf-8", errors="replace").strip()
            err_text = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode == 0 and output:
                return AgentResult(
                    agent_name=self.name, output=output, success=True,
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
                agent_name=self.name, output="", success=False,
                error=f"Claude Code timed out after {self._timeout}s",
                duration_ms=(time.time() - start) * 1000,
            )
        except FileNotFoundError:
            return await self._api_fallback(task, start)
        except Exception as exc:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=str(exc), duration_ms=(time.time() - start) * 1000,
            )

    # ── API fallback ──────────────────────────────────────────────────────────

    async def _api_fallback(self, task: str, start: float) -> AgentResult:
        """Used when the claude CLI binary is not installed."""
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
        except Exception as exc:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=f"CLI unavailable and API fallback failed: {exc}",
                duration_ms=(time.time() - start) * 1000,
            )

    # ── Health check ──────────────────────────────────────────────────────────

    async def health_check(self) -> AgentHealthStatus:
        start = time.time()
        cli_name = self._cli_path.split()[0] if " " in self._cli_path else self._cli_path
        cli = shutil.which(cli_name)
        if not cli:
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
        except Exception as exc:
            return AgentHealthStatus(
                agent_name=self.name,
                status=AgentStatus.UNAVAILABLE,
                detail=str(exc),
                latency_ms=(time.time() - start) * 1000,
            )
