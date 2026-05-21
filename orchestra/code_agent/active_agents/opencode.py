from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import time
import uuid
from typing import Any, Callable

from orchestra.code_agent.active_agents.base import (
    ActiveAgent, AgentCapability, AgentHealthStatus, AgentResult, AgentStatus,
)

_DEFAULT_PORT = 4096
_SERVE_TIMEOUT = 10   # seconds to wait for server to start
_DONE_TYPES = frozenset({
    "session.error", "message.error", "error",
    "assistant.stop", "step.finish", "message.stop",
    "session.complete", "complete",
})
_ASSISTANT_TYPES = frozenset({
    "assistant", "message.assistant", "step.text",
    "text.delta", "content_block_delta", "text",
})


def _make_cmd(cli: str, args: list[str]) -> list[str]:
    if platform.system() == "Windows" and cli.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", cli, *args]
    return [cli, *args]


class OpenCodeAgent(ActiveAgent):
    """Driver for OpenCode (sst/opencode) — open-source AI coding agent.

    Starts `opencode serve` as a subprocess, drives it via its HTTP API,
    and falls back to the Anthropic API if the CLI is unavailable.
    """

    name = "opencode"
    display_name = "OpenCode"
    priority = 15
    capabilities = [
        AgentCapability(
            name="coding",
            description="Agentic code editing with file read/write/edit tools",
            intent_keywords=["code", "implement", "write", "edit", "refactor", "fix", "build"],
        ),
        AgentCapability(
            name="debug",
            description="Debugging, error tracing, and root-cause analysis",
            intent_keywords=["debug", "fix bug", "error", "crash", "traceback", "exception"],
        ),
        AgentCapability(
            name="explain",
            description="Code explanation and documentation",
            intent_keywords=["explain", "document", "what does", "how does", "describe"],
        ),
        AgentCapability(
            name="test",
            description="Test generation and coverage improvements",
            intent_keywords=["test", "unit test", "pytest", "spec", "coverage"],
        ),
    ]

    def __init__(
        self,
        cli_path: str | None = None,
        model: str | None = None,
        provider: str | None = None,
        timeout: int = 300,
        api_key: str | None = None,
    ):
        self._cli_path = cli_path or self._default_cli_path()
        self._model = model or os.environ.get("OPENCODE_MODEL", "claude-sonnet-4-6")
        self._provider = provider or os.environ.get("OPENCODE_PROVIDER", "anthropic")
        self._timeout = timeout
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    async def execute(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        event_callback: Callable | None = None,
    ) -> AgentResult:
        ctx = context or {}
        start = time.time()

        if event_callback is not None:
            await _emit(event_callback, {
                "type": "agent_init",
                "data": {
                    "agent": self.name,
                    "display_name": self.display_name,
                    "model": self._model,
                    "engine": self.name,
                    "mode": "serve_http",
                },
            })

        cli = self._resolve_cli()
        if cli:
            try:
                return await self._run_via_server(cli, task, ctx, start, event_callback)
            except Exception as e:
                if not self._api_key:
                    return AgentResult(
                        agent_name=self.name, output="", success=False,
                        error=f"opencode serve failed: {e}",
                        duration_ms=(time.time() - start) * 1000,
                    )

        return await self._api_fallback(task, ctx, start, event_callback)

    # ── HTTP-server path ───────────────────────────────────────────────────

    async def _run_via_server(
        self,
        cli: str,
        task: str,
        ctx: dict,
        start: float,
        event_callback: Callable | None,
    ) -> AgentResult:
        import httpx

        cwd = ctx.get("cwd")
        cmd = _make_cmd(cli, ["serve", "--port", "0"])
        env = {**os.environ, "ANTHROPIC_API_KEY": self._api_key or os.environ.get("ANTHROPIC_API_KEY", "")}

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        port = await self._find_port(proc)
        if not port:
            proc.kill()
            await proc.wait()
            raise RuntimeError("opencode serve: could not determine port within timeout")

        base = f"http://127.0.0.1:{port}"

        try:
            async with httpx.AsyncClient(base_url=base, timeout=30) as client:
                # Create session
                sess_resp = await client.post("/session", json={
                    "modelID": self._model,
                    "providerID": self._provider,
                    "model": {
                        "id": self._model,
                        "providerID": self._provider,
                        "variant": "default",
                    },
                })
                sess_resp.raise_for_status()
                session_id = sess_resp.json()["id"]

                if event_callback is not None:
                    await _emit(event_callback, {
                        "type": "text",
                        "data": {"text": f"[OpenCode] Session {session_id} created\n"},
                    })

                # Send prompt
                prompt_resp = await client.post(f"/session/{session_id}/prompt_async", json={
                    "modelID": self._model,
                    "providerID": self._provider,
                    "parts": [{"type": "text", "text": task}],
                })
                prompt_resp.raise_for_status()

                # Poll messages until assistant response arrives
                output = await self._poll_response(
                    client, session_id, event_callback, deadline=start + self._timeout
                )

                return AgentResult(
                    agent_name=self.name,
                    output=output,
                    success=bool(output),
                    duration_ms=(time.time() - start) * 1000,
                    metadata={"via": "opencode_serve", "model": self._model, "session": session_id},
                )
        finally:
            try:
                proc.kill()
                await asyncio.wait_for(proc.wait(), timeout=5)
            except Exception:
                pass

    async def _find_port(self, proc: asyncio.subprocess.Process) -> int | None:
        """Read stderr until we find the listening port."""
        deadline = time.time() + _SERVE_TIMEOUT
        buf = b""
        assert proc.stderr is not None
        while time.time() < deadline:
            try:
                chunk = await asyncio.wait_for(proc.stderr.read(256), timeout=1)
                if not chunk:
                    break
                buf += chunk
                m = re.search(rb"listening on http://127\.0\.0\.1:(\d+)", buf)
                if m:
                    return int(m.group(1))
                # Also check stdout
                if proc.stdout:
                    try:
                        out_chunk = await asyncio.wait_for(proc.stdout.read(256), timeout=0.1)
                        m2 = re.search(rb"listening on http://127\.0\.0\.1:(\d+)", out_chunk)
                        if m2:
                            return int(m2.group(1))
                    except asyncio.TimeoutError:
                        pass
            except asyncio.TimeoutError:
                continue
        return None

    async def _poll_response(
        self,
        client: Any,
        session_id: str,
        event_callback: Callable | None,
        deadline: float,
    ) -> str:
        """Poll GET /api/session/{id}/message until assistant content arrives."""
        seen_ids: set[str] = set()
        text_parts: list[str] = []
        cursor_next: str | None = None

        while time.time() < deadline:
            url = f"/api/session/{session_id}/message"
            params: dict = {}
            if cursor_next:
                params["cursor"] = cursor_next

            try:
                resp = await client.get(url, params=params)
                resp.raise_for_status()
                data = resp.json()
            except Exception:
                await asyncio.sleep(1)
                continue

            items = data.get("items", [])
            cursor_info = data.get("cursor", {})
            cursor_next = cursor_info.get("next")

            for item in items:
                item_id = item.get("id", "")
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)

                ev_type = item.get("type", "")
                text = _extract_text(item)
                if text:
                    text_parts.append(text)
                    if event_callback is not None:
                        await _emit(event_callback, {"type": "text", "data": {"text": text}})

                if ev_type in _DONE_TYPES:
                    return "".join(text_parts)

            # If we have content and no more items, wait a bit then check for completion
            if text_parts and not items:
                await asyncio.sleep(2)
                # One more poll to check for done event
                try:
                    resp2 = await client.get(url, params={"cursor": cursor_next} if cursor_next else {})
                    data2 = resp2.json()
                    if not data2.get("items"):
                        # No new events — likely done
                        if text_parts:
                            return "".join(text_parts)
                except Exception:
                    pass

            await asyncio.sleep(1.5)

        return "".join(text_parts)

    # ── Anthropic API fallback ────────────────────────────────────────────

    async def _api_fallback(
        self,
        task: str,
        ctx: dict,
        start: float,
        event_callback: Callable | None,
    ) -> AgentResult:
        if not self._api_key:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error="opencode CLI not found and ANTHROPIC_API_KEY not set",
                duration_ms=(time.time() - start) * 1000,
            )
        model = self._model or "claude-sonnet-4-6"
        try:
            import anthropic as _anthropic
            client = _anthropic.AsyncAnthropic(api_key=self._api_key)
            system = (
                "You are OpenCode, an expert AI software engineering assistant. "
                "Write correct, complete, idiomatic code. No placeholders."
            )
            scaffold = ctx.get("append_system_prompt", "")
            if scaffold:
                system += "\n\n" + scaffold

            if event_callback is not None:
                collected: list[str] = []
                async with client.messages.stream(
                    model=model, max_tokens=8192, system=system,
                    messages=[{"role": "user", "content": task}],
                ) as stream:
                    async for text in stream.text_stream:
                        collected.append(text)
                        await _emit(event_callback, {"type": "text", "data": {"text": text}})
                output = "".join(collected)
            else:
                msg = await client.messages.create(
                    model=model, max_tokens=8192, system=system,
                    messages=[{"role": "user", "content": task}],
                )
                output = msg.content[0].text if msg.content else ""

            return AgentResult(
                agent_name=self.name, output=output, success=bool(output),
                duration_ms=(time.time() - start) * 1000,
                metadata={"via": "anthropic_api_fallback", "model": model},
            )
        except Exception as e:
            return AgentResult(
                agent_name=self.name, output="", success=False,
                error=str(e), duration_ms=(time.time() - start) * 1000,
            )

    # ── Health check ──────────────────────────────────────────────────────

    async def health_check(self) -> AgentHealthStatus:
        start = time.time()
        cli = self._resolve_cli()
        if cli:
            try:
                cmd = _make_cmd(cli, ["--version"])
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
                version = stdout.decode("utf-8", errors="replace").strip()
                return AgentHealthStatus(
                    agent_name=self.name,
                    status=AgentStatus.AVAILABLE,
                    version=version or "unknown",
                    latency_ms=(time.time() - start) * 1000,
                    detail=f"opencode CLI at {cli} (serve mode)",
                )
            except Exception:
                pass

        if os.environ.get("ANTHROPIC_API_KEY"):
            return AgentHealthStatus(
                agent_name=self.name,
                status=AgentStatus.DEGRADED,
                latency_ms=(time.time() - start) * 1000,
                detail="CLI unavailable; using Anthropic API fallback",
            )
        return AgentHealthStatus(
            agent_name=self.name,
            status=AgentStatus.UNAVAILABLE,
            detail="opencode CLI not found and ANTHROPIC_API_KEY not set",
        )

    # ── Helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _default_cli_path() -> str:
        env = os.environ.get("ORCHESTRA_OPENCODE_CLI")
        if env:
            return env
        for name in ("opencode", "opencode.cmd", "opencode.CMD"):
            found = shutil.which(name)
            if found:
                return found
        return "opencode"

    def _resolve_cli(self) -> str | None:
        from pathlib import Path
        candidate = Path(self._cli_path)
        if candidate.is_file():
            return str(candidate)
        found = shutil.which(self._cli_path)
        if found:
            return found
        if platform.system() == "Windows":
            for name in ("opencode.cmd", "opencode.CMD", "opencode.exe"):
                found = shutil.which(name)
                if found:
                    return found
        return shutil.which("opencode")


# ── Module-level helpers ──────────────────────────────────────────────────

async def _emit(callback: Callable, event: dict) -> None:
    maybe = callback(event)
    if asyncio.iscoroutine(maybe):
        await maybe


def _extract_text(item: dict) -> str:
    """Pull assistant text out of an opencode message event."""
    ev_type = item.get("type", "")

    # Direct text field
    text = item.get("text", "")
    if text and isinstance(text, str):
        return text

    # Content field (string or list)
    content = item.get("content", "")
    if isinstance(content, str) and content:
        return content
    if isinstance(content, list):
        parts = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") in ("text", "text_delta"):
                    parts.append(c.get("text", ""))
                elif c.get("type") == "content_block_delta":
                    parts.append(c.get("delta", {}).get("text", ""))
        result = "".join(parts)
        if result:
            return result

    # Parts field (opencode message format)
    parts_list = item.get("parts", [])
    if isinstance(parts_list, list):
        chunks = []
        for p in parts_list:
            if isinstance(p, dict) and p.get("type") == "text":
                chunks.append(p.get("text", ""))
        if chunks:
            return "".join(chunks)

    return ""
