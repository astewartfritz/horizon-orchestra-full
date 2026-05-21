from __future__ import annotations

import json
import logging
import time
from typing import Any

from orchestra.code_agent.agent_headers.context import ContextManager
from orchestra.code_agent.agent_headers.freshness import FreshnessTracker
from orchestra.code_agent.agent_headers.identity import HumanVsAIPolicy, parse_agent_type
from orchestra.code_agent.agent_headers.intent import IntentRouter, parse_intent
from orchestra.code_agent.agent_headers.models import AgentRole, AgentType, RateLimitPolicy
from orchestra.code_agent.agent_headers.ratelimit import RateLimitStore, parse_error_recovery
from orchestra.code_agent.agent_headers.role import RolePolicy, parse_agent_role
from orchestra.code_agent.agent_headers.tokens import AgentTokenManager, parse_agent_token

__all__ = [
    "AgentHeadersMiddleware",
    "register_agent_headers_middleware",
]

log = logging.getLogger("orchestra.agent_headers.middleware")


class AgentHeadersContext:
    """Holds parsed agent header state for a single request."""

    def __init__(self) -> None:
        self.agent_id: str = ""
        self.agent_role: AgentRole = AgentRole.SYSTEM
        self.agent_type: AgentType = AgentType.HUMAN
        self.intent: str = ""
        self.context_id: str = ""
        self.token: str = ""
        self.staleness_seconds: float = 0.0
        self.error_recovery: dict[str, Any] = {}
        self.rate_limit_result: dict[str, int] | None = None
        self.role_config: dict[str, object] = {}
        self.identity_policy: dict[str, object] = {}
        self.context_data: dict[str, Any] | None = None


class AgentHeadersMiddleware:
    """ASGI middleware that processes all agent-specific headers.

    Processes:
    - ``X-Agent-Context-Id`` → session continuity
    - ``X-Agent-Intent`` → intent-based routing
    - ``X-Agent-Role`` → role-based response tailoring
    - ``X-Agent-Type`` → AI vs human differentiation
    - ``X-Agent-Token`` → agent verification
    - ``X-Data-Staleness-Accept`` → data freshness
    - ``X-Error-Recovery`` → error recovery guidance

    Adds response headers:
    - ``X-Data-LastUpdated``
    - ``X-RateLimit-Remaining``, ``X-RateLimit-Reset``, ``X-RateLimit-Limit``
    - ``X-Error-Recovery``
    """

    def __init__(
        self,
        app: Any,
        context_manager: ContextManager | None = None,
        intent_router: IntentRouter | None = None,
        role_policy: RolePolicy | None = None,
        identity_policy: HumanVsAIPolicy | None = None,
        token_manager: AgentTokenManager | None = None,
        freshness_tracker: FreshnessTracker | None = None,
        rate_limit_store: RateLimitStore | None = None,
    ) -> None:
        self.app = app
        self.context = context_manager or ContextManager()
        self.intent_router = intent_router or IntentRouter()
        self.role_policy = role_policy or RolePolicy()
        self.identity_policy = identity_policy or HumanVsAIPolicy()
        self.token_manager = token_manager or AgentTokenManager()
        self.freshness = freshness_tracker or FreshnessTracker()
        self.ratelimit = rate_limit_store or RateLimitStore()

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = self._parse_headers(scope)
        ctx = self._process_headers(headers, scope)

        original_send = send

        async def patched_send(message: dict) -> None:
            if message.get("type") == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.extend(self._build_response_headers(ctx))
                message["headers"] = response_headers
            await original_send(message)

        await self.app(scope, receive, patched_send)

    def _parse_headers(self, scope: dict) -> dict[str, str]:
        raw = dict(scope.get("headers", []))
        return {k.decode(): v.decode() for k, v in raw.items()}

    def _process_headers(self, headers: dict[str, str], scope: dict) -> AgentHeadersContext:
        ctx = AgentHeadersContext()

        # Agent token → verify identity
        token_str = parse_agent_token(headers)
        ctx.token = token_str
        if token_str:
            claims = self.token_manager.verify_token(token_str)
            if claims:
                ctx.agent_id = claims.agent_id
                ctx.agent_role = claims.agent_role
                ctx.agent_type = claims.agent_type

        # Role header (overrides token role if present)
        role = parse_agent_role(headers)
        ctx.agent_role = role
        ctx.role_config = self.role_policy.get_config(role)

        # Identity header (AI vs human)
        agent_type = parse_agent_type(headers)
        if agent_type != AgentType.HUMAN or not ctx.agent_id:
            ctx.agent_type = agent_type
        ctx.identity_policy = self.identity_policy.get_policy(ctx.agent_type)

        # Intent header
        intent = parse_intent(headers)
        ctx.intent = intent.value

        # Context ID → session continuity
        ctx.context_id = headers.get(ContextManager.header_name(), "")
        if ctx.context_id:
            record = self.context.get_context(ctx.context_id)
            if record:
                ctx.context_data = record.data
                self.context.update_context(ctx.context_id, {"last_access": time.time()})

        # Staleness accept
        ctx.staleness_seconds = self.freshness.parse_staleness_accept(headers)

        # Error recovery header
        ctx.error_recovery = parse_error_recovery(headers)

        # Rate limit check
        agent_id = ctx.agent_id or scope.get("client", ("unknown",))[0]
        rate_policy = RateLimitPolicy(
            requests_per_minute=ctx.identity_policy.get("max_requests_per_min", 60),
            requests_per_hour=1000,
            burst_size=10,
        )
        ctx.rate_limit_result = self.ratelimit.check(agent_id, rate_policy)

        return ctx

    def _build_response_headers(self, ctx: AgentHeadersContext) -> list[tuple[bytes, bytes]]:
        hdrs: list[tuple[bytes, bytes]] = []

        # Rate limit headers
        if ctx.rate_limit_result:
            for name, value in self.ratelimit.format_headers(ctx.rate_limit_result):
                hdrs.append((name.encode(), value.encode()))

        return hdrs


def register_agent_headers_middleware(app: Any, **kwargs: Any) -> None:
    """Register the agent headers middleware on a FastAPI app."""
    try:
        from fastapi import FastAPI
        if not isinstance(app, FastAPI):
            raise TypeError("Expected a FastAPI instance")
    except ImportError:
        raise ImportError("fastapi is required. Install with: pip install code-agent[server]")

    app.add_middleware(AgentHeadersMiddleware, **kwargs)
    log.info("AgentHeadersMiddleware registered")
