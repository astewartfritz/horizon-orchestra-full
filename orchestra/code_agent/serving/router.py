from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from orchestra.code_agent.llm.base import LLMError, Message
from orchestra.code_agent.serving.base import BaseProvider, ProviderConfig
from orchestra.code_agent.serving.factory import ProviderFactory
from orchestra.code_agent.serving.registry import ModelCapability, ModelRegistry


class RoutingStrategy(Enum):
    CAPABILITY = "capability"
    CHEAPEST = "cheapest"
    FASTEST = "fastest"
    FALLBACK = "fallback"
    ROUND_ROBIN = "round_robin"
    WEIGHTED = "weighted"
    CUSTOM = "custom"


@dataclass
class RouteTarget:
    provider: str
    model: str
    weight: float = 1.0
    max_retries: int = 1
    timeout: float = 120.0
    overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class RouterRule:
    name: str
    strategy: RoutingStrategy = RoutingStrategy.FALLBACK
    targets: list[RouteTarget] = field(default_factory=list)
    required_capability: ModelCapability | None = None
    min_context_window: int = 0
    max_cost_per_million: float = float("inf")
    priority: int = 0

    def matches(self, task: str, context: dict[str, Any] | None = None) -> bool:
        return True


@dataclass
class RouterResult:
    success: bool = False
    output: str = ""
    provider: str = ""
    model: str = ""
    attempts: list[dict[str, Any]] = field(default_factory=list)
    total_latency: float = 0.0
    router_rule: str = ""


class ModelRouter:
    def __init__(
        self,
        registry: ModelRegistry | None = None,
        rules: list[RouterRule] | None = None,
    ):
        self.registry = registry or ModelRegistry()
        self.rules = rules or self._default_rules()
        self._cache: dict[str, Any] = {}

    def _default_rules(self) -> list[RouterRule]:
        return [
            RouterRule(
                name="prefer-cheapest",
                strategy=RoutingStrategy.CHEAPEST,
                required_capability=ModelCapability.CHAT,
                priority=1,
            ),
            RouterRule(
                name="fallback-chain",
                strategy=RoutingStrategy.FALLBACK,
                targets=[
                    RouteTarget(provider="openai", model="gpt-4o", weight=1.0),
                    RouteTarget(provider="openai", model="gpt-4o-mini", weight=1.0),
                    RouteTarget(provider="anthropic", model="claude-sonnet-4-20250514", weight=1.0),
                    RouteTarget(provider="ollama", model="llama3.1", weight=1.0),
                ],
                priority=0,
            ),
            RouterRule(
                name="streaming-optimized",
                strategy=RoutingStrategy.CHEAPEST,
                required_capability=ModelCapability.STREAMING,
                priority=2,
            ),
        ]

    def add_rule(self, rule: RouterRule) -> None:
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def _select_strategy_targets(self, rule: RouterRule) -> list[RouteTarget]:
        if rule.strategy == RoutingStrategy.FALLBACK:
            return rule.targets

        if rule.strategy == RoutingStrategy.CHEAPEST:
            cap = rule.required_capability or ModelCapability.CHAT
            models = self.registry.find_by_capability(cap, rule.min_context_window)
            filtered = [m for m in models if m.cost_per_million_input <= rule.max_cost_per_million]
            if not filtered:
                return rule.targets or [RouteTarget(provider="openai", model="gpt-4o")]
            return [RouteTarget(provider=m.provider, model=m.model_id) for m in filtered[:3]]

        if rule.strategy == RoutingStrategy.FASTEST:
            models = self.registry.list_models()
            sorted_models = sorted(
                models,
                key=lambda m: (m.latency_p50_ms if m.latency_p50_ms > 0 else 500),
            )
            return [RouteTarget(provider=m.provider, model=m.model_id) for m in sorted_models[:3]]

        if rule.strategy == RoutingStrategy.ROUND_ROBIN:
            targets = rule.targets
            idx = self._cache.get("rr_index", 0) % max(len(targets), 1)
            self._cache["rr_index"] = idx + 1
            return [targets[idx]]

        if rule.strategy == RoutingStrategy.WEIGHTED:
            if not rule.targets:
                return [RouteTarget(provider="openai", model="gpt-4o")]
            total = sum(t.weight for t in rule.targets)
            r = random.uniform(0, total)
            cumulative = 0.0
            for target in rule.targets:
                cumulative += target.weight
                if r <= cumulative:
                    return [target]
            return [rule.targets[-1]]

        return rule.targets

    def select_route(self, task: str, context: dict[str, Any] | None = None) -> list[RouteTarget]:
        for rule in sorted(self.rules, key=lambda r: r.priority, reverse=True):
            if rule.matches(task, context):
                targets = self._select_strategy_targets(rule)
                if targets:
                    return targets
        return [RouteTarget(provider="openai", model="gpt-4o")]

    async def route_chat(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | None = None,
        stream: bool = False,
        task: str = "",
        context: dict[str, Any] | None = None,
    ) -> RouterResult:
        targets = self.select_route(task, context)
        result = RouterResult()
        start = time.time()

        for target in targets:
            attempt: dict[str, Any] = {
                "provider": target.provider,
                "model": target.model,
                "status": "pending",
            }
            try:
                cfg = ProviderConfig(
                    timeout=target.timeout,
                    **(target.overrides or {}),
                )
                provider = ProviderFactory.create(target.provider, target.model, cfg)
                response = await provider.chat(messages, tools, tool_choice, stream=stream)
                content = response.content if isinstance(response, Message) else str(response)
                attempt["status"] = "success"
                attempt["output_preview"] = content[:200]
                result.attempts.append(attempt)
                result.success = True
                result.output = content
                result.provider = target.provider
                result.model = target.model
                break
            except Exception as e:
                attempt["status"] = "error"
                attempt["error"] = str(e)
                result.attempts.append(attempt)

        result.total_latency = time.time() - start
        return result

    def clear_cache(self) -> None:
        self._cache.clear()
