from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from code_agent.active_agents.base import AgentResult, AgentStatus
from code_agent.active_agents.registry import ActiveAgentRegistry
from code_agent.nemotron.classifier import ClassificationResult, NemotronClassifier

logger = logging.getLogger(__name__)


@dataclass
class RoutingDecision:
    classification: ClassificationResult
    selected_agent: str
    fallback_chain: list[str] = field(default_factory=list)
    health_filtered: bool = False
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "classification": self.classification.to_dict(),
            "selected_agent": self.selected_agent,
            "fallback_chain": self.fallback_chain,
            "health_filtered": self.health_filtered,
            "duration_ms": self.duration_ms,
        }


class NemotronRouter:
    """Routes tasks to the best active agent using Nemotron classification.

    Pipeline:
      1. Run health checks on all registered agents
      2. Filter to available/degraded agents
      3. Ask NemotronClassifier to select the best agent for the task
      4. Validate selection is healthy; fall back if not
      5. Return RoutingDecision
    """

    def __init__(
        self,
        registry: ActiveAgentRegistry,
        classifier: NemotronClassifier | None = None,
        confidence_threshold: float = 0.3,
    ):
        self._registry = registry
        self._classifier = classifier or NemotronClassifier()
        self._confidence_threshold = confidence_threshold

    async def route(
        self,
        task: str,
        skip_health_check: bool = False,
    ) -> RoutingDecision:
        start = time.time()

        if not skip_health_check:
            health = await self._registry.run_health_checks()
        else:
            health = self._registry._health_cache

        available = self._registry.available_agents(health)
        health_filtered = len(available) < len(self._registry.all_agents())

        if not available:
            # No agents healthy — try all anyway
            available = self._registry.all_agents()

        agent_dicts = [a.to_dict() for a in available]
        classification = await self._classifier.classify(task, agent_dicts)

        # Validate Nemotron's choice is in our available set
        available_names = {a.name for a in available}
        selected = classification.agent_name

        if selected not in available_names or classification.confidence < self._confidence_threshold:
            # Fall back to highest-priority available agent
            selected = available[0].name if available else ""
            logger.debug(
                "Nemotron chose '%s' (conf=%.2f); overriding to '%s'",
                classification.agent_name,
                classification.confidence,
                selected,
            )

        # Build fallback chain: Nemotron's fallbacks ∩ available, then remaining available
        nemotron_fallbacks = [
            n for n in classification.fallback_agents if n in available_names and n != selected
        ]
        remaining = [
            a.name for a in available if a.name != selected and a.name not in nemotron_fallbacks
        ]
        fallback_chain = nemotron_fallbacks + remaining

        return RoutingDecision(
            classification=classification,
            selected_agent=selected,
            fallback_chain=fallback_chain,
            health_filtered=health_filtered,
            duration_ms=(time.time() - start) * 1000,
        )

    async def route_and_execute(
        self,
        task: str,
        context: dict[str, Any] | None = None,
        skip_health_check: bool = False,
    ) -> tuple[RoutingDecision, AgentResult]:
        decision = await self.route(task, skip_health_check=skip_health_check)
        if not decision.selected_agent:
            result = AgentResult(
                agent_name="nemotron_router",
                output="",
                success=False,
                error="No agents available to handle task",
            )
            return decision, result

        # Try selected agent, then fallbacks
        chain = [decision.selected_agent] + decision.fallback_chain
        last_result: AgentResult | None = None

        for name in chain:
            agent = self._registry.get(name)
            if not agent:
                continue
            logger.debug("Dispatching task to %s", name)
            result = await agent.execute(task, context)
            if result.success:
                return decision, result
            last_result = result
            logger.debug("Agent %s failed, trying fallback", name)

        if last_result:
            return decision, last_result

        result = AgentResult(
            agent_name="nemotron_router",
            output="",
            success=False,
            error="All agents in fallback chain failed",
        )
        return decision, result
