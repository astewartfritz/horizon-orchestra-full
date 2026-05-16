"""Billing middleware for Horizon Orchestra architectures.

Wraps any architecture backend (A–E) with pre-run limit checks,
real-time usage tracking during execution, and post-run metering.
Drop this in front of any architecture's ``run()`` / ``stream()``
method for automatic billing integration.

Usage::

    from orchestra.billing.middleware import BillingMiddleware

    middleware = BillingMiddleware(billing_manager)
    wrapped = middleware.wrap(my_agent, architecture="C")

    # Now wrapped.run() and wrapped.stream() enforce limits
    result = await wrapped.run("Build a dashboard")

Or use the decorator style::

    @billing_gate(billing_manager, architecture="B")
    async def research(query: str) -> str:
        pipeline = RAGPipeline()
        return await pipeline.run(query)
"""
from __future__ import annotations

import asyncio
import functools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Awaitable

from .architecture_billing import (
    Architecture,
    ArchitectureBillingManager,
    ArchitectureLimits,
    CostEstimate,
    ARCHITECTURE_PROFILES,
    estimate_cost,
)

__all__ = [
    "BillingMiddleware",
    "BillingWrappedAgent",
    "BillingEvent",
    "billing_gate",
]

logger = logging.getLogger("orchestra.billing.middleware")


# ---------------------------------------------------------------------------
# Billing events (emitted alongside agent events in the stream)
# ---------------------------------------------------------------------------

@dataclass
class BillingEvent:
    """Event emitted by the billing middleware during execution.

    Injected into the stream alongside normal AgentEvents so the
    UI can show real-time cost tracking.
    """

    type: str                    # "billing_check" | "billing_update" | "billing_limit" | "billing_complete"
    architecture: str
    user_id: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "architecture": self.architecture,
            "user_id": self.user_id,
            "data": self.data,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Billing-wrapped agent
# ---------------------------------------------------------------------------

class BillingWrappedAgent:
    """Wraps any architecture backend with billing enforcement.

    Intercepts ``run()`` and ``stream()`` calls to:

    1. **Pre-flight** — check architecture access and tier limits
    2. **Mid-flight** — track token/tool-call consumption in real-time
    3. **Post-flight** — record final usage to the billing meter
    """

    def __init__(
        self,
        agent: Any,
        architecture: str,
        user_id: str,
        billing_manager: ArchitectureBillingManager,
    ) -> None:
        self._agent = agent
        self._arch = Architecture.from_str(architecture)
        self._user_id = user_id
        self._mgr = billing_manager
        self._run_count = 0

    @property
    def agent(self) -> Any:
        """Access the underlying unwrapped agent."""
        return self._agent

    async def run(self, task: str, **kwargs: Any) -> str:
        """Execute a task with billing enforcement."""
        # Pre-flight check
        access = await self._mgr.check_access(self._user_id, self._arch.value)
        if not access["allowed"]:
            raise PermissionError(
                f"Billing: {access['reason']} "
                f"Upgrade options: {access.get('upgrade_options', [])}"
            )

        start = time.monotonic()
        tokens_used = 0
        tool_calls = 0

        try:
            result = await self._agent.run(task, **kwargs)

            # Estimate tokens from result length (rough heuristic)
            tokens_used = len(result) // 4 if isinstance(result, str) else 0
            tool_calls = getattr(self._agent, "last_tool_call_count", 0)

            return result
        finally:
            elapsed = time.monotonic() - start
            await self._record_run(tokens_used, tool_calls, elapsed)

    async def stream(self, task: str, **kwargs: Any) -> AsyncGenerator[Any, None]:
        """Stream events with billing enforcement and real-time tracking."""
        # Pre-flight check
        access = await self._mgr.check_access(self._user_id, self._arch.value)
        if not access["allowed"]:
            yield BillingEvent(
                type="billing_limit",
                architecture=self._arch.value,
                user_id=self._user_id,
                data={
                    "reason": access["reason"],
                    "upgrade_options": access.get("upgrade_options", []),
                },
            )
            return

        # Emit pre-flight check event
        estimate = self._mgr.estimate(
            self._user_id, self._arch.value,
            tokens=ARCHITECTURE_PROFILES[self._arch].avg_tokens_per_run,
            tool_calls=ARCHITECTURE_PROFILES[self._arch].avg_tool_calls_per_run,
        )
        yield BillingEvent(
            type="billing_check",
            architecture=self._arch.value,
            user_id=self._user_id,
            data={
                "estimate": {
                    "total_units": estimate.total_units,
                    "multiplier": estimate.multiplier,
                    "within_limits": estimate.within_tier_limits,
                },
                "tier": estimate.tier,
            },
        )

        start = time.monotonic()
        tokens_used = 0
        tool_calls = 0
        sub_agents = 0

        try:
            async for event in self._agent.stream(task, **kwargs):
                # Track usage mid-stream
                event_type = getattr(event, "type", "")
                if event_type == "tool_call":
                    tool_calls += 1
                elif event_type == "token":
                    content = getattr(event, "content", "")
                    tokens_used += max(1, len(content) // 4)
                elif event_type == "spawn_agent":
                    sub_agents += 1

                # Emit periodic billing updates (every 10 tool calls)
                if tool_calls > 0 and tool_calls % 10 == 0:
                    yield BillingEvent(
                        type="billing_update",
                        architecture=self._arch.value,
                        user_id=self._user_id,
                        data={
                            "tokens": tokens_used,
                            "tool_calls": tool_calls,
                            "sub_agents": sub_agents,
                            "elapsed_s": round(time.monotonic() - start, 1),
                        },
                    )

                yield event

        finally:
            elapsed = time.monotonic() - start
            await self._record_run(
                tokens_used, tool_calls, elapsed,
                swarm_agents=sub_agents,
            )

            # Emit completion event
            yield BillingEvent(
                type="billing_complete",
                architecture=self._arch.value,
                user_id=self._user_id,
                data={
                    "tokens": tokens_used,
                    "tool_calls": tool_calls,
                    "sub_agents": sub_agents,
                    "elapsed_s": round(elapsed, 1),
                    "cost_units": round(
                        estimate_cost(
                            self._arch.value, "free",
                            tokens=tokens_used, tool_calls=tool_calls,
                            sub_agents=sub_agents,
                        ).total_units,
                        4,
                    ),
                },
            )

    async def stream_sse(self, task: str, **kwargs: Any) -> AsyncGenerator[Any, None]:
        """SSE streaming with billing (delegates to wrapped stream_sse)."""
        access = await self._mgr.check_access(self._user_id, self._arch.value)
        if not access["allowed"]:
            raise PermissionError(
                f"Billing: {access['reason']} "
                f"Upgrade options: {access.get('upgrade_options', [])}"
            )

        if hasattr(self._agent, "stream_sse"):
            start = time.monotonic()
            tokens = 0
            async for chunk in self._agent.stream_sse(task, **kwargs):
                tokens += 1
                yield chunk

            await self._record_run(tokens * 4, 0, time.monotonic() - start)
        else:
            async for event in self.stream(task, **kwargs):
                yield event

    async def run_long_horizon(self, task: str, user_id: str = "", **kwargs: Any) -> Any:
        """Long-horizon execution with billing enforcement."""
        uid = user_id or self._user_id

        # Check long-horizon specific limits
        check = await self._mgr.check_run_limits(
            uid, self._arch.value, long_horizon_hours=4.0,
        )
        if not check["allowed"]:
            raise PermissionError(
                f"Billing: {'; '.join(check['violations'])}"
            )

        # Track long-horizon start
        await self._mgr.record(
            uid, self._arch.value, long_horizon_delta=1,
        )

        try:
            if hasattr(self._agent, "run_long_horizon"):
                return await self._agent.run_long_horizon(task, uid, **kwargs)
            else:
                return await self._agent.run(task, **kwargs)
        finally:
            # Track long-horizon end
            await self._mgr.record(
                uid, self._arch.value, long_horizon_delta=-1,
            )

    async def _record_run(
        self,
        tokens: int,
        tool_calls: int,
        elapsed: float,
        *,
        swarm_agents: int = 0,
    ) -> None:
        """Record a completed run to the billing meter."""
        self._run_count += 1
        await self._mgr.record(
            self._user_id,
            self._arch.value,
            tokens=tokens,
            tool_calls=tool_calls,
            swarm_agents=swarm_agents,
        )
        logger.info(
            "Billing recorded: arch=%s user=%s run=%d tokens=%d calls=%d "
            "elapsed=%.1fs",
            self._arch.value, self._user_id, self._run_count,
            tokens, tool_calls, elapsed,
        )

    def __getattr__(self, name: str) -> Any:
        """Proxy all other attributes to the underlying agent."""
        return getattr(self._agent, name)


# ---------------------------------------------------------------------------
# Billing middleware factory
# ---------------------------------------------------------------------------

class BillingMiddleware:
    """Factory that wraps architecture backends with billing enforcement.

    Usage::

        middleware = BillingMiddleware(billing_manager)

        # Wrap individual agents
        agent_a = MonolithicAgent()
        billed_a = middleware.wrap(agent_a, architecture="A", user_id="user123")

        # Or wrap the ProductionOrchestrator
        orch = ProductionOrchestrator(config=ProductionConfig(architecture="C"))
        billed_orch = middleware.wrap(orch, architecture="C", user_id="user123")
    """

    def __init__(self, billing_manager: ArchitectureBillingManager) -> None:
        self._mgr = billing_manager

    def wrap(
        self,
        agent: Any,
        architecture: str,
        user_id: str = "default",
    ) -> BillingWrappedAgent:
        """Wrap an agent with billing enforcement.

        Args:
            agent: Any architecture backend (MonolithicAgent, RAGPipeline,
                   SwarmAgent, MCPToolHub, ProductionOrchestrator).
            architecture: Which architecture this agent implements ("A"-"E").
            user_id: The user executing the task.

        Returns:
            A BillingWrappedAgent that enforces tier limits on all calls.
        """
        return BillingWrappedAgent(
            agent=agent,
            architecture=architecture,
            user_id=user_id,
            billing_manager=self._mgr,
        )

    async def check_and_wrap(
        self,
        agent: Any,
        architecture: str,
        user_id: str = "default",
    ) -> BillingWrappedAgent:
        """Check access first, then wrap (raises PermissionError if denied)."""
        access = await self._mgr.check_access(user_id, architecture)
        if not access["allowed"]:
            raise PermissionError(
                f"Architecture {architecture} not available: {access['reason']}"
            )
        return self.wrap(agent, architecture, user_id)


# ---------------------------------------------------------------------------
# Decorator for billing gating
# ---------------------------------------------------------------------------

def billing_gate(
    billing_manager: ArchitectureBillingManager,
    architecture: str,
    user_id_arg: str = "user_id",
) -> Callable:
    """Decorator that gates an async function behind billing checks.

    Usage::

        @billing_gate(mgr, architecture="B")
        async def research(query: str, user_id: str = "default") -> str:
            pipeline = RAGPipeline()
            return await pipeline.run(query)

    The decorated function must accept a ``user_id`` keyword argument
    (or whatever ``user_id_arg`` specifies).
    """
    def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            uid = kwargs.get(user_id_arg, "default")
            access = await billing_manager.check_access(uid, architecture)
            if not access["allowed"]:
                raise PermissionError(
                    f"Billing: {access['reason']} "
                    f"Upgrade options: {access.get('upgrade_options', [])}"
                )
            return await fn(*args, **kwargs)
        return wrapper
    return decorator
