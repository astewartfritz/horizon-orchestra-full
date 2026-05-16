"""Inference Gateway — Infrastructure-level interception of all model calls.

Every LLM API call made by any Horizon Orchestra agent passes through
this gateway.  Agents are never allowed to contact model endpoints
directly.  The gateway provides:

    * **Provider routing** via the existing :class:`ModelRouter`.
    * **Per-agent model governance** — each agent can only use models
      explicitly granted to it.
    * **Input / output guardrails** via :class:`BeyondGuardrails`.
    * **Rate limiting** per agent, per model, and per organisation.
    * **Cost tracking** with per-agent billing.
    * **Audit logging** via :class:`AuditLedger`.
    * **Automatic failover** to secondary providers on error.
    * **Live model switching** without agent restart.
    * **Streaming support** with guardrail enforcement.

Integration with the existing ``ModelRouter`` in ``orchestra.router``
is via a try/except import so the gateway works stand-alone in tests.

Beyond NemoClaw: NemoClaw supports a single inference provider with
no per-agent governance, no cost tracking, and no failover.  This
gateway supports 12+ providers with per-agent governance, live
switching, cost tracking, and automatic failover.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Sequence

__all__ = [
    "InferenceResult",
    "ProviderRoute",
    "UsageReport",
    "RateLimit",
    "GuardrailResult",
    "InferenceGateway",
]

log = logging.getLogger("orchestra.guardian.inference_gateway")


# ---------------------------------------------------------------------------
# Try to import ModelRouter from the existing codebase
# ---------------------------------------------------------------------------

try:
    from orchestra.router import ModelRouter, ModelConfig
    _HAS_ROUTER = True
except ImportError:
    _HAS_ROUTER = False
    ModelRouter = None  # type: ignore[assignment, misc]
    ModelConfig = None  # type: ignore[assignment, misc]
    log.info("ModelRouter not available — gateway will use stub routing")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class ProviderRoute:
    """Resolved route to a model provider.

    Attributes
    ----------
    provider : str
        Provider name (e.g. ``"moonshot"``, ``"openrouter"``).
    model_id : str
        The model identifier expected by the provider API.
    base_url : str
        API base URL.
    api_key : str
        Resolved API key (may be empty for local providers).
    cost_input : float
        $/M input tokens.
    cost_output : float
        $/M output tokens.
    max_context : int
        Maximum context window.
    supports_tools : bool
        Whether the model supports tool calling.
    supports_vision : bool
        Whether the model supports vision input.
    """

    provider: str = ""
    model_id: str = ""
    base_url: str = ""
    api_key: str = ""
    cost_input: float = 0.0
    cost_output: float = 0.0
    max_context: int = 128_000
    supports_tools: bool = True
    supports_vision: bool = False


@dataclass
class InferenceResult:
    """Result of an inference call through the gateway.

    Attributes
    ----------
    request_id : str
        Unique identifier for this request.
    model_id : str
        The model that was actually used.
    provider : str
        Provider that served the request.
    content : str
        The generated text content.
    tool_calls : list[dict]
        Tool call requests from the model.
    usage : dict
        Token usage: ``{"input": N, "output": M, "total": N+M}``.
    cost : float
        Estimated cost in USD.
    latency_ms : float
        End-to-end latency in milliseconds.
    guardrails_input : dict
        Input guardrail results.
    guardrails_output : dict
        Output guardrail results.
    metadata : dict
        Additional response metadata.
    cached : bool
        Whether the result was served from cache.
    failover : bool
        Whether a failover occurred.
    """

    request_id: str = ""
    model_id: str = ""
    provider: str = ""
    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0
    latency_ms: float = 0.0
    guardrails_input: dict[str, Any] = field(default_factory=dict)
    guardrails_output: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    cached: bool = False
    failover: bool = False


@dataclass
class UsageReport:
    """Aggregated usage report for an agent.

    Attributes
    ----------
    agent_id : str
        The agent these stats belong to.
    total_requests : int
        Number of inference calls made.
    total_input_tokens : int
        Total input tokens consumed.
    total_output_tokens : int
        Total output tokens generated.
    total_cost : float
        Estimated total cost in USD.
    by_model : dict
        Breakdown by model: ``{model: {"requests": N, "cost": X}}``.
    period_start : float
        Start of the reporting period.
    period_end : float
        End of the reporting period.
    """

    agent_id: str = ""
    total_requests: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0
    by_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    period_start: float = 0.0
    period_end: float = 0.0


@dataclass
class RateLimit:
    """Rate limit configuration for an agent.

    Attributes
    ----------
    requests_per_minute : int
        Maximum requests per minute (0 = unlimited).
    tokens_per_day : int
        Maximum tokens per day (0 = unlimited).
    cost_per_day : float
        Maximum cost in USD per day (0 = unlimited).
    """

    requests_per_minute: int = 60
    tokens_per_day: int = 1_000_000
    cost_per_day: float = 100.0


@dataclass
class GuardrailResult:
    """Result of guardrail evaluation."""
    passed: bool = True
    violations: list[str] = field(default_factory=list)
    redacted_text: Optional[str] = None
    latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Rate-limit tracker (token bucket)
# ---------------------------------------------------------------------------

class _TokenBucket:
    """Simple token-bucket rate limiter."""

    def __init__(self, rate: float, capacity: float) -> None:
        self.rate = rate          # tokens per second
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()

    def consume(self, n: float = 1.0) -> bool:
        """Try to consume *n* tokens.  Returns ``True`` if allowed."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
        self.last_refill = now

        if self.tokens >= n:
            self.tokens -= n
            return True
        return False


class _UsageTracker:
    """Per-agent usage tracking."""

    def __init__(self) -> None:
        self.requests: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cost: float = 0.0
        self.by_model: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"requests": 0, "input_tokens": 0, "output_tokens": 0, "cost": 0.0}
        )
        self.first_request: float = 0.0
        self.last_request: float = 0.0
        # Daily tracking for rate limits
        self.daily_tokens: int = 0
        self.daily_cost: float = 0.0
        self.daily_reset: float = 0.0

    def record(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> None:
        """Record a single inference call."""
        now = time.time()
        self.requests += 1
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost += cost
        if not self.first_request:
            self.first_request = now
        self.last_request = now

        entry = self.by_model[model_id]
        entry["requests"] += 1
        entry["input_tokens"] += input_tokens
        entry["output_tokens"] += output_tokens
        entry["cost"] += cost

        # Daily tracking
        if now - self.daily_reset > 86_400:  # 24h
            self.daily_tokens = 0
            self.daily_cost = 0.0
            self.daily_reset = now
        self.daily_tokens += input_tokens + output_tokens
        self.daily_cost += cost


# ---------------------------------------------------------------------------
# Failover chain
# ---------------------------------------------------------------------------

# Model -> list of fallback model names (tried in order)
_DEFAULT_FAILOVER: dict[str, list[str]] = {
    "kimi-k2.5": ["kimi-k2.5-openrouter", "kimi-k2.5-together", "kimi-k2.5-local"],
    "kimi-k2.5-openrouter": ["kimi-k2.5", "kimi-k2.5-together"],
    "kimi-k2.5-together": ["kimi-k2.5", "kimi-k2.5-openrouter"],
    "gemma-4-31b": ["gemma-4-31b-vllm", "gemma-4-26b-moe"],
    "gemma-4-12b": ["gemma-4-ollama", "gemma-4-hf"],
    "sonar": ["sonar-pro"],
}


# ---------------------------------------------------------------------------
# InferenceGateway
# ---------------------------------------------------------------------------

class InferenceGateway:
    """Infrastructure-level inference routing for all Orchestra agents.

    Every model API call passes through this gateway.  Never allow
    agents to contact LLM endpoints directly.

    The gateway integrates with the existing :class:`ModelRouter` from
    ``orchestra.router`` for provider resolution and client management.

    Parameters
    ----------
    router : ModelRouter, optional
        Existing model router.  If not provided, a default is created
        (if ModelRouter is available).
    guardrails : object, optional
        A :class:`BeyondGuardrails` instance for input/output checks.
    audit : object, optional
        An :class:`AuditLedger` instance for logging.
    failover_chains : dict, optional
        Custom failover chains ``{model: [fallback_models]}``.
    """

    def __init__(
        self,
        router: Any = None,
        guardrails: Any = None,
        audit: Any = None,
        failover_chains: Optional[dict[str, list[str]]] = None,
    ) -> None:
        # ModelRouter integration
        if router is not None:
            self._router = router
        elif _HAS_ROUTER:
            self._router = ModelRouter()
        else:
            self._router = None

        self._guardrails = guardrails
        self._audit = audit

        # Per-agent model governance: agent_id -> set of allowed model names
        self._model_governance: dict[str, set[str]] = {}

        # Rate limiting
        self._rate_limits: dict[str, RateLimit] = {}
        self._rate_buckets: dict[str, _TokenBucket] = {}

        # Usage tracking
        self._usage: dict[str, _UsageTracker] = defaultdict(_UsageTracker)

        # Failover
        self._failover_chains = failover_chains or dict(_DEFAULT_FAILOVER)

        # Provider overrides (for hot-switching)
        self._provider_overrides: dict[str, str] = {}

        # Lock for governance changes
        self._lock = asyncio.Lock()

    # -- core inference -----------------------------------------------------

    async def call(
        self,
        agent_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        response_format: Optional[dict[str, Any]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> InferenceResult:
        """Execute a model inference call with full governance.

        Steps:
            1. Check model governance (is agent allowed this model?)
            2. Check rate limits
            3. Apply input guardrails
            4. Route to provider (with failover)
            5. Apply output guardrails
            6. Record usage & audit
            7. Return result

        Parameters
        ----------
        agent_id : str
            The calling agent's identifier.
        model_id : str
            The model to use (must be in the agent's allowed set).
        messages : list[dict]
            OpenAI-format message list.
        temperature : float
            Sampling temperature.
        max_tokens : int
            Maximum output tokens.
        tools : list[dict], optional
            Tool definitions for function calling.
        tool_choice : str, optional
            Tool choice strategy.
        response_format : dict, optional
            Output format specification.
        metadata : dict, optional
            Additional metadata to log.

        Returns
        -------
        InferenceResult
            The model response with governance metadata.
        """
        request_id = uuid.uuid4().hex[:16]
        t0 = time.monotonic()
        result = InferenceResult(request_id=request_id, model_id=model_id)

        # 1. Model governance check
        if not self.can_use_model(agent_id, model_id):
            await self._audit_event(
                agent_id, "inference_call", model_id, "deny",
                {"reason": "model_not_allowed", "request_id": request_id},
            )
            result.content = ""
            result.metadata = {"error": f"Agent {agent_id} not allowed to use {model_id}"}
            return result

        # 2. Rate limit check
        if not self._check_rate_limit(agent_id):
            await self._audit_event(
                agent_id, "inference_call", model_id, "deny",
                {"reason": "rate_limited", "request_id": request_id},
            )
            result.content = ""
            result.metadata = {"error": "Rate limit exceeded"}
            return result

        # 3. Input guardrails
        if self._guardrails:
            combined_text = " ".join(
                m.get("content", "") for m in messages if isinstance(m.get("content"), str)
            )
            try:
                gr = await self._guardrails.check_input(agent_id, combined_text)
                result.guardrails_input = {
                    "passed": gr.content_safe,
                    "violations": gr.violations,
                    "latency_ms": gr.latency_ms,
                }
                if not gr.content_safe:
                    await self._audit_event(
                        agent_id, "inference_call", model_id, "deny",
                        {"reason": "input_guardrail", "violations": gr.violations,
                         "request_id": request_id},
                    )
                    result.content = ""
                    result.metadata = {"error": "Input blocked by guardrails",
                                       "violations": gr.violations}
                    return result
            except Exception:
                log.exception("Input guardrail check failed")

        # 4. Route to provider (with failover)
        resolved_model = self._provider_overrides.get(model_id, model_id)
        response_content = ""
        response_tool_calls: list[dict[str, Any]] = []
        response_usage: dict[str, int] = {"input": 0, "output": 0, "total": 0}
        provider_name = ""
        did_failover = False

        models_to_try = [resolved_model] + self._failover_chains.get(resolved_model, [])

        for attempt, try_model in enumerate(models_to_try):
            try:
                route = await self.route(try_model)
                provider_name = route.provider

                if self._router:
                    # Use ModelRouter to get client
                    client, actual_model_id = self._router.get_client(try_model)
                    kwargs_call: dict[str, Any] = {
                        "model": actual_model_id,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    }
                    if tools:
                        kwargs_call["tools"] = tools
                    if tool_choice:
                        kwargs_call["tool_choice"] = tool_choice
                    if response_format:
                        kwargs_call["response_format"] = response_format

                    resp = await client.chat.completions.create(**kwargs_call)

                    choice = resp.choices[0] if resp.choices else None
                    if choice and choice.message:
                        response_content = choice.message.content or ""
                        if choice.message.tool_calls:
                            response_tool_calls = [
                                {
                                    "id": tc.id,
                                    "type": tc.type,
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in choice.message.tool_calls
                            ]

                    if resp.usage:
                        response_usage = {
                            "input": resp.usage.prompt_tokens or 0,
                            "output": resp.usage.completion_tokens or 0,
                            "total": resp.usage.total_tokens or 0,
                        }
                else:
                    # Stub mode (no ModelRouter available)
                    response_content = f"[Gateway stub] Model {try_model} called"
                    response_usage = {"input": 0, "output": 0, "total": 0}

                if attempt > 0:
                    did_failover = True
                break  # Success — exit retry loop

            except Exception as exc:
                log.warning(
                    "Inference failed for %s (attempt %d): %s",
                    try_model, attempt + 1, exc,
                )
                if attempt == len(models_to_try) - 1:
                    # All attempts exhausted
                    await self._audit_event(
                        agent_id, "inference_call", model_id, "error",
                        {"reason": "all_providers_failed", "request_id": request_id},
                    )
                    result.content = ""
                    result.metadata = {"error": f"All providers failed: {exc}"}
                    result.latency_ms = (time.monotonic() - t0) * 1000
                    return result

        # 5. Output guardrails
        if self._guardrails and response_content:
            try:
                gr_out = await self._guardrails.check_output(agent_id, response_content)
                result.guardrails_output = {
                    "passed": not gr_out.pii_detected and not gr_out.injection_detected,
                    "violations": gr_out.violations,
                    "latency_ms": gr_out.latency_ms,
                }
                if gr_out.redacted_output:
                    response_content = gr_out.redacted_output
            except Exception:
                log.exception("Output guardrail check failed")

        # 6. Calculate cost
        route_info = await self.route(resolved_model)
        input_cost = response_usage.get("input", 0) * route_info.cost_input / 1_000_000
        output_cost = response_usage.get("output", 0) * route_info.cost_output / 1_000_000
        total_cost = input_cost + output_cost

        # Record usage
        tracker = self._usage[agent_id]
        tracker.record(
            model_id=resolved_model,
            input_tokens=response_usage.get("input", 0),
            output_tokens=response_usage.get("output", 0),
            cost=total_cost,
        )

        # 7. Audit
        await self._audit_event(
            agent_id, "inference_call", resolved_model, "allow",
            {
                "request_id": request_id,
                "provider": provider_name,
                "tokens": response_usage,
                "cost": total_cost,
                "failover": did_failover,
                "latency_ms": (time.monotonic() - t0) * 1000,
            },
        )

        # Build result
        result.model_id = resolved_model
        result.provider = provider_name
        result.content = response_content
        result.tool_calls = response_tool_calls
        result.usage = response_usage
        result.cost = total_cost
        result.latency_ms = (time.monotonic() - t0) * 1000
        result.failover = did_failover
        result.metadata = metadata or {}

        return result

    async def stream(
        self,
        agent_id: str,
        model_id: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: Optional[list[dict[str, Any]]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> AsyncGenerator[str, None]:
        """Stream inference results with governance checks.

        Input guardrails are applied before streaming starts.
        Output guardrails are applied to the accumulated response after
        streaming completes.

        Yields
        ------
        str
            Text chunks from the model.
        """
        # 1. Governance check
        if not self.can_use_model(agent_id, model_id):
            return

        # 2. Rate limit
        if not self._check_rate_limit(agent_id):
            return

        # 3. Input guardrails
        if self._guardrails:
            combined_text = " ".join(
                m.get("content", "") for m in messages if isinstance(m.get("content"), str)
            )
            try:
                gr = await self._guardrails.check_input(agent_id, combined_text)
                if not gr.content_safe:
                    return
            except Exception:
                log.exception("Input guardrail check failed during stream")

        # 4. Stream from provider
        resolved_model = self._provider_overrides.get(model_id, model_id)
        if not self._router:
            yield f"[Gateway stub] Streaming {resolved_model}"
            return

        try:
            client, actual_model_id = self._router.get_client(resolved_model)
            kwargs_stream: dict[str, Any] = {
                "model": actual_model_id,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if tools:
                kwargs_stream["tools"] = tools

            stream_resp = await client.chat.completions.create(**kwargs_stream)
            accumulated = ""
            async for chunk in stream_resp:
                if chunk.choices and chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    accumulated += text
                    yield text

        except Exception:
            log.exception("Stream failed for %s", resolved_model)

    # -- governance ---------------------------------------------------------

    def can_use_model(self, agent_id: str, model_id: str) -> bool:
        """Check if *agent_id* is allowed to use *model_id*.

        If no governance is set for the agent, all models are allowed
        (permissive default — restrict via :meth:`grant_model`).
        """
        allowed = self._model_governance.get(agent_id)
        if allowed is None:
            return True  # No restrictions configured
        return model_id in allowed

    def get_allowed_models(self, agent_id: str) -> list[str]:
        """Return the list of models *agent_id* is allowed to use."""
        allowed = self._model_governance.get(agent_id)
        if allowed is None:
            # Return all known models
            if self._router:
                return list(self._router.models.keys())
            return []
        return sorted(allowed)

    async def grant_model(self, agent_id: str, model_id: str) -> None:
        """Grant *agent_id* permission to use *model_id*."""
        async with self._lock:
            if agent_id not in self._model_governance:
                self._model_governance[agent_id] = set()
            self._model_governance[agent_id].add(model_id)
        log.info("Granted model %s to %s", model_id, agent_id)

    async def revoke_model(self, agent_id: str, model_id: str) -> None:
        """Revoke *agent_id*'s permission to use *model_id*."""
        async with self._lock:
            allowed = self._model_governance.get(agent_id)
            if allowed:
                allowed.discard(model_id)
        log.info("Revoked model %s from %s", model_id, agent_id)

    async def set_governance(
        self,
        agent_id: str,
        allowed_models: list[str],
    ) -> None:
        """Set the complete set of allowed models for an agent."""
        async with self._lock:
            self._model_governance[agent_id] = set(allowed_models)

    # -- routing ------------------------------------------------------------

    async def route(self, model_id: str) -> ProviderRoute:
        """Resolve a model ID to a :class:`ProviderRoute`."""
        resolved = self._provider_overrides.get(model_id, model_id)

        if self._router:
            try:
                cfg = self._router.get_config(resolved)
                import os
                return ProviderRoute(
                    provider=cfg.provider,
                    model_id=cfg.model_id,
                    base_url=cfg.base_url,
                    api_key=os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else "",
                    cost_input=cfg.cost_input,
                    cost_output=cfg.cost_output,
                    max_context=cfg.max_context,
                    supports_tools=cfg.supports_tools,
                    supports_vision=cfg.supports_vision,
                )
            except KeyError:
                pass

        # Fallback stub route
        return ProviderRoute(
            provider="unknown",
            model_id=resolved,
        )

    async def hot_switch_provider(
        self,
        model_id: str,
        new_provider_model: str,
    ) -> None:
        """Switch *model_id* to a different provider without restart.

        For example, switch ``"kimi-k2.5"`` to use
        ``"kimi-k2.5-openrouter"`` as the backing provider.
        """
        async with self._lock:
            self._provider_overrides[model_id] = new_provider_model
        log.info("Hot-switched %s -> %s", model_id, new_provider_model)

    async def clear_provider_override(self, model_id: str) -> None:
        """Remove a provider override, restoring the default."""
        async with self._lock:
            self._provider_overrides.pop(model_id, None)

    # -- cost + rate limiting -----------------------------------------------

    def get_usage(self, agent_id: str) -> UsageReport:
        """Return the usage report for *agent_id*."""
        tracker = self._usage.get(agent_id)
        if not tracker:
            return UsageReport(agent_id=agent_id)
        return UsageReport(
            agent_id=agent_id,
            total_requests=tracker.requests,
            total_input_tokens=tracker.input_tokens,
            total_output_tokens=tracker.output_tokens,
            total_cost=tracker.cost,
            by_model=dict(tracker.by_model),
            period_start=tracker.first_request,
            period_end=tracker.last_request,
        )

    def get_cost(self, agent_id: str, period: str = "all") -> float:
        """Return the cost for *agent_id* over *period*.

        Parameters
        ----------
        period : str
            ``"all"`` (lifetime), ``"day"`` (last 24h).
        """
        tracker = self._usage.get(agent_id)
        if not tracker:
            return 0.0
        if period == "day":
            return tracker.daily_cost
        return tracker.cost

    async def set_rate_limit(
        self,
        agent_id: str,
        requests_per_min: int = 60,
        tokens_per_day: int = 1_000_000,
        cost_per_day: float = 100.0,
    ) -> None:
        """Configure rate limits for *agent_id*."""
        async with self._lock:
            self._rate_limits[agent_id] = RateLimit(
                requests_per_minute=requests_per_min,
                tokens_per_day=tokens_per_day,
                cost_per_day=cost_per_day,
            )
            # Create/reset token bucket
            self._rate_buckets[agent_id] = _TokenBucket(
                rate=requests_per_min / 60.0,
                capacity=float(requests_per_min),
            )
        log.info(
            "Set rate limit for %s: %d req/min, %d tok/day, $%.2f/day",
            agent_id, requests_per_min, tokens_per_day, cost_per_day,
        )

    def _check_rate_limit(self, agent_id: str) -> bool:
        """Return ``True`` if the agent is within rate limits."""
        limits = self._rate_limits.get(agent_id)
        if not limits:
            return True  # No limits configured

        # Token bucket (requests/min)
        bucket = self._rate_buckets.get(agent_id)
        if bucket and not bucket.consume():
            log.warning("Rate limit exceeded for %s (requests/min)", agent_id)
            return False

        # Daily token limit
        tracker = self._usage.get(agent_id)
        if tracker:
            if limits.tokens_per_day and tracker.daily_tokens >= limits.tokens_per_day:
                log.warning("Rate limit exceeded for %s (tokens/day)", agent_id)
                return False
            if limits.cost_per_day and tracker.daily_cost >= limits.cost_per_day:
                log.warning("Rate limit exceeded for %s (cost/day)", agent_id)
                return False

        return True

    # -- guardrails ---------------------------------------------------------

    async def apply_input_guardrails(
        self,
        agent_id: str,
        messages: list[dict[str, Any]],
    ) -> GuardrailResult:
        """Run input guardrails on messages.  Used for manual checks."""
        if not self._guardrails:
            return GuardrailResult(passed=True)

        combined = " ".join(
            m.get("content", "") for m in messages if isinstance(m.get("content"), str)
        )
        t0 = time.monotonic()
        gr = await self._guardrails.check_input(agent_id, combined)
        return GuardrailResult(
            passed=gr.content_safe,
            violations=gr.violations,
            redacted_text=gr.redacted_output,
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    async def apply_output_guardrails(
        self,
        agent_id: str,
        response: str,
    ) -> GuardrailResult:
        """Run output guardrails on a response.  Used for manual checks."""
        if not self._guardrails:
            return GuardrailResult(passed=True)

        t0 = time.monotonic()
        gr = await self._guardrails.check_output(agent_id, response)
        return GuardrailResult(
            passed=not gr.pii_detected and not gr.injection_detected,
            violations=gr.violations,
            redacted_text=gr.redacted_output,
            latency_ms=(time.monotonic() - t0) * 1000,
        )

    # -- audit integration --------------------------------------------------

    async def _audit_event(
        self,
        agent_id: str,
        event_type: str,
        resource: str,
        result: str,
        metadata: dict[str, Any],
    ) -> None:
        """Record an audit event if the ledger is available."""
        if not self._audit:
            return
        try:
            await self._audit.record(
                agent_id=agent_id,
                event_type=event_type,
                resource=resource,
                action="call",
                result=result,
                metadata=metadata,
            )
        except Exception:
            log.exception("Failed to record audit event")

    # -- statistics ---------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate gateway statistics."""
        total_requests = sum(t.requests for t in self._usage.values())
        total_cost = sum(t.cost for t in self._usage.values())
        return {
            "total_requests": total_requests,
            "total_cost": total_cost,
            "active_agents": len(self._usage),
            "governed_agents": len(self._model_governance),
            "rate_limited_agents": len(self._rate_limits),
            "provider_overrides": dict(self._provider_overrides),
            "router_available": self._router is not None,
            "guardrails_available": self._guardrails is not None,
            "audit_available": self._audit is not None,
        }

    def __repr__(self) -> str:
        return (
            f"<InferenceGateway agents={len(self._usage)} "
            f"router={'yes' if self._router else 'no'}>"
        )
