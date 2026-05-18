from __future__ import annotations

import asyncio
import logging
from typing import Any

from code_agent.active_agents.base import (
    ActiveAgent, AgentHealthStatus, AgentResult, AgentStatus,
)

logger = logging.getLogger(__name__)


class ActiveAgentRegistry:
    """Central registry for all active agent drivers.

    Agents are stored in priority order (lower = higher priority).
    Health checks run lazily and are cached per health_check() call.
    """

    def __init__(self) -> None:
        self._agents: dict[str, ActiveAgent] = {}
        self._health_cache: dict[str, AgentHealthStatus] = {}

    def register(self, agent: ActiveAgent) -> None:
        self._agents[agent.name] = agent
        logger.debug("Registered agent: %s (priority=%d)", agent.name, agent.priority)

    def unregister(self, name: str) -> bool:
        if name in self._agents:
            del self._agents[name]
            self._health_cache.pop(name, None)
            return True
        return False

    def get(self, name: str) -> ActiveAgent | None:
        return self._agents.get(name)

    def all_agents(self) -> list[ActiveAgent]:
        return sorted(self._agents.values(), key=lambda a: a.priority)

    def agents_for_intent(self, intent: str) -> list[ActiveAgent]:
        """Return agents that can handle the given intent, sorted by priority."""
        return sorted(
            [a for a in self._agents.values() if a.can_handle(intent)],
            key=lambda a: a.priority,
        )

    def agents_by_capability(self, capability: str) -> list[ActiveAgent]:
        """Return agents that declare a specific capability name."""
        return sorted(
            [a for a in self._agents.values() if capability in a.capability_names()],
            key=lambda a: a.priority,
        )

    async def run_health_checks(self) -> dict[str, AgentHealthStatus]:
        """Run health checks for all registered agents concurrently."""
        async def _check(agent: ActiveAgent) -> tuple[str, AgentHealthStatus]:
            try:
                status = await agent.health_check()
            except Exception as e:
                status = AgentHealthStatus(
                    agent_name=agent.name,
                    status=AgentStatus.UNAVAILABLE,
                    detail=f"health_check raised: {e}",
                )
            return agent.name, status

        results = await asyncio.gather(*[_check(a) for a in self._agents.values()])
        self._health_cache = dict(results)
        return self._health_cache

    def available_agents(
        self, health: dict[str, AgentHealthStatus] | None = None
    ) -> list[ActiveAgent]:
        """Return agents whose last health status is AVAILABLE or DEGRADED."""
        cache = health or self._health_cache
        available_statuses = {AgentStatus.AVAILABLE, AgentStatus.DEGRADED}
        return sorted(
            [
                a for a in self._agents.values()
                if cache.get(a.name, AgentHealthStatus(a.name, AgentStatus.UNKNOWN)).status
                in available_statuses
            ],
            key=lambda a: a.priority,
        )

    async def execute_with_fallback(
        self,
        task: str,
        intent: str = "",
        context: dict[str, Any] | None = None,
        max_fallbacks: int = 2,
    ) -> AgentResult:
        """Execute task using best-matching agent, falling back on failure."""
        candidates = self.agents_for_intent(intent) if intent else self.all_agents()

        if not candidates:
            from code_agent.active_agents.base import AgentResult
            return AgentResult(
                agent_name="registry",
                output="",
                success=False,
                error="No agents registered",
            )

        attempted: list[str] = []
        last_result: AgentResult | None = None

        for agent in candidates[: max_fallbacks + 1]:
            logger.debug("Attempting task with agent: %s", agent.name)
            result = await agent.execute(task, context)
            attempted.append(agent.name)
            if result.success:
                result.metadata["attempted_agents"] = attempted
                return result
            last_result = result
            logger.debug("Agent %s failed: %s", agent.name, result.error)

        if last_result:
            last_result.metadata["attempted_agents"] = attempted
            return last_result

        from code_agent.active_agents.base import AgentResult
        return AgentResult(
            agent_name="registry",
            output="",
            success=False,
            error="All agents failed",
            metadata={"attempted_agents": attempted},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "agents": [a.to_dict() for a in self.all_agents()],
            "count": len(self._agents),
        }


def build_default_registry() -> ActiveAgentRegistry:
    """Build a registry pre-populated with all built-in active agents."""
    registry = ActiveAgentRegistry()

    try:
        from code_agent.active_agents.claude_code import ClaudeCodeAgent
        registry.register(ClaudeCodeAgent())
    except Exception as e:
        logger.warning("Could not load ClaudeCodeAgent: %s", e)

    try:
        from code_agent.active_agents.codex import CodexAgent
        registry.register(CodexAgent())
    except Exception as e:
        logger.warning("Could not load CodexAgent: %s", e)

    try:
        from code_agent.active_agents.openclaw import OpenClawAgent
        registry.register(OpenClawAgent())
    except Exception as e:
        logger.warning("Could not load OpenClawAgent: %s", e)

    return registry
