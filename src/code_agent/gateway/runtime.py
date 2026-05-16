from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable

from code_agent import Agent, AgentConfig
from code_agent.config import LLMConfig
from code_agent.gateway.policy import PolicyEngine, PolicyDecision
from code_agent.gateway.skills import SkillsRegistry
from code_agent.gateway.webhooks import WebhookManager
from code_agent.channels.manager import ChannelManager, ChannelType, Message


@dataclass
class GatewayEvent:
    """Normalized internal envelope for all inbound events."""
    id: str = ""
    channel: ChannelType = ChannelType.CLI
    sender: str = "user"
    content: str = ""
    session_id: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


class AgentRuntime:
    """Full AI loop: context assembly → LLM → tool interception → stream → persist.

    Each turn phase is observable via hooks:
    ingest → auth → route → resolve → context → invoke → intercept → format → deliver → persist
    """

    def __init__(self, config: AgentConfig | None = None):
        self.config = config or AgentConfig(llm=LLMConfig(provider="ollama", model="nemotron-mini"))
        self.logger = logging.getLogger("orchestra.runtime")
        self._agents: dict[str, Agent] = {}
        self._hooks: dict[str, list[Callable]] = {
            "ingest": [], "auth": [], "route": [], "resolve": [],
            "context": [], "invoke": [], "intercept": [], "format": [],
            "deliver": [], "persist": [],
        }

    def on(self, phase: str, hook: Callable) -> None:
        if phase in self._hooks:
            self._hooks[phase].append(hook)

    async def _run_phase(self, phase: str, ctx: dict[str, Any]) -> dict[str, Any]:
        for hook in self._hooks.get(phase, []):
            try:
                result = hook(ctx)
                if asyncio.iscoroutine(result):
                    result = await result
                if result:
                    ctx.update(result)
            except Exception as e:
                self.logger.warning("Hook %s failed: %s", phase, e)
        return ctx

    def _get_or_create_agent(self, session_id: str) -> Agent:
        if session_id not in self._agents:
            agent = Agent(self.config)
            self._agents[session_id] = agent
        return self._agents[session_id]

    async def process_event(self, event: GatewayEvent) -> str:
        ctx = {
            "event": event,
            "session_id": event.session_id or event.id,
            "agent": self._get_or_create_agent(event.session_id or event.id),
            "result": "",
            "tools_called": [],
            "latency": 0.0,
        }
        start = time.time()

        try:
            ctx = await self._run_phase("ingest", ctx)
            ctx = await self._run_phase("auth", ctx)
            ctx = await self._run_phase("route", ctx)
            ctx = await self._run_phase("resolve", ctx)
            ctx = await self._run_phase("context", ctx)

            agent: Agent = ctx["agent"]
            result = await agent.run(event.content, stream=True)
            ctx["result"] = result

            ctx = await self._run_phase("intercept", ctx)
            ctx = await self._run_phase("format", ctx)

        except Exception as e:
            self.logger.exception("Runtime error")
            ctx["result"] = f"Error: {e}"

        ctx["latency"] = time.time() - start
        ctx = await self._run_phase("deliver", ctx)
        ctx = await self._run_phase("persist", ctx)

        return ctx.get("result", "")


class Gateway:
    """Single entry point for all external channels.

    Normalizes events, authenticates, routes to session, dispatches to runtime.
    Centralizes session management, platform bindings, and access control.
    """

    def __init__(self, runtime: AgentRuntime | None = None):
        self.runtime = runtime or AgentRuntime()
        self.channels = ChannelManager()
        self.policy = PolicyEngine()
        self.skills = SkillsRegistry()
        self.webhooks = WebhookManager()
        self.logger = logging.getLogger("orchestra.gateway")
        self._sessions: dict[str, dict[str, Any]] = {}
        self._api_keys: dict[str, str] = {}  # key → session_id

    def register_api_key(self, key: str, session_id: str) -> None:
        self._api_keys[key] = session_id

    def authenticate(self, api_key: str | None = None, sender: str = "") -> str | None:
        if api_key and api_key in self._api_keys:
            return self._api_keys[api_key]
        if sender in ("cli", "web", "repl"):
            return "default"
        return None

    async def handle_event(self, event: GatewayEvent, api_key: str | None = None) -> str:
        session_id = self.authenticate(api_key, event.sender)
        if not session_id:
            raise PermissionError("Authentication required")
        event.session_id = session_id

        # Policy check
        decision = self.policy.check(event.content, event.sender, session_id)
        if decision == PolicyDecision.DENY:
            return "Blocked by policy."

        # Route to runtime
        return await self.runtime.process_event(event)

    def get_session(self, session_id: str) -> dict[str, Any]:
        return self._sessions.get(session_id, {})

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())
