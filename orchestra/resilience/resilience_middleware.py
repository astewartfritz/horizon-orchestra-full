"""
resilience_middleware.py — Drop-in ``@resilient`` decorator for Horizon Orchestra.

Wraps any async function with the full resilience stack:
circuit breaker → adaptive retry → recovery graph → fallback chain.

Records all outcomes for telemetry and learning.

Example::

    @resilient(circuit_breaker="moonshot", retry_policy="model_errors", fallback="kimi_down")
    async def call_model(prompt: str) -> str:
        ...
"""
from __future__ import annotations

__all__ = [
    "ResilientConfig",
    "ResilientOutcome",
    "ResilientCall",
    "resilient",
]

import asyncio
import functools
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Optional, TypeVar

from .adaptive_retry import AdaptiveRetryManager, RetryDecision
from .circuit_breaker import CircuitBreaker, CircuitState
from .error_taxonomy import ErrorTaxonomy
from .fallback_chain import FallbackChain, FallbackScenario
from .recovery_graph import RecoveryGraph

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ResilientConfig:
    """Configuration for the resilient decorator.

    Attributes:
        provider: Provider name for circuit breaker tracking.
        model: Model name for circuit breaker tracking.
        retry_error_types: Error types that trigger adaptive retry.
        fallback_scenario: Which fallback chain to use on total failure.
        enable_circuit_breaker: Whether to check circuit breaker.
        enable_retry: Whether to apply adaptive retry.
        enable_recovery_graph: Whether to traverse recovery graph.
        enable_fallback: Whether to use fallback chain.
        operation: Operation label for circuit breaker.
    """
    provider: str = ""
    model: str = ""
    retry_error_types: list[str] = field(default_factory=list)
    fallback_scenario: Optional[FallbackScenario] = None
    enable_circuit_breaker: bool = True
    enable_retry: bool = True
    enable_recovery_graph: bool = True
    enable_fallback: bool = True
    operation: str = "chat"


# ---------------------------------------------------------------------------
# Outcome record
# ---------------------------------------------------------------------------

@dataclass
class ResilientOutcome:
    """Complete record of a resilient call execution.

    Attributes:
        succeeded: Whether the call eventually succeeded.
        total_latency_ms: Wall-clock time for the entire resilient call.
        attempts: Total attempts (original + retries).
        circuit_breaker_blocked: Whether the circuit breaker blocked the call.
        retry_count: Number of retries attempted.
        recovery_used: Which recovery node was used, if any.
        fallback_used: Whether a fallback target was used.
        fallback_position: Position in the fallback chain, if applicable.
        error_code: Classified error code, if any.
        error_message: Raw error message, if any.
    """
    succeeded: bool
    total_latency_ms: float = 0.0
    attempts: int = 1
    circuit_breaker_blocked: bool = False
    retry_count: int = 0
    recovery_used: str = ""
    fallback_used: bool = False
    fallback_position: int = -1
    error_code: str = ""
    error_message: str = ""


# ---------------------------------------------------------------------------
# Shared singleton instances (lazily initialised)
# ---------------------------------------------------------------------------

_circuit_breaker: Optional[CircuitBreaker] = None
_retry_manager: Optional[AdaptiveRetryManager] = None
_recovery_graph: Optional[RecoveryGraph] = None
_fallback_chain: Optional[FallbackChain] = None
_taxonomy: Optional[ErrorTaxonomy] = None
_outcome_log: list[ResilientOutcome] = []


def _get_circuit_breaker() -> CircuitBreaker:
    global _circuit_breaker
    if _circuit_breaker is None:
        _circuit_breaker = CircuitBreaker()
    return _circuit_breaker


def _get_retry_manager() -> AdaptiveRetryManager:
    global _retry_manager
    if _retry_manager is None:
        _retry_manager = AdaptiveRetryManager()
    return _retry_manager


def _get_recovery_graph() -> RecoveryGraph:
    global _recovery_graph
    if _recovery_graph is None:
        _recovery_graph = RecoveryGraph()
    return _recovery_graph


def _get_fallback_chain() -> FallbackChain:
    global _fallback_chain
    if _fallback_chain is None:
        _fallback_chain = FallbackChain()
    return _fallback_chain


def _get_taxonomy() -> ErrorTaxonomy:
    global _taxonomy
    if _taxonomy is None:
        _taxonomy = ErrorTaxonomy()
    return _taxonomy


# ---------------------------------------------------------------------------
# ResilientCall — the execution engine
# ---------------------------------------------------------------------------

class ResilientCall:
    """Orchestrates the full resilience stack for a single call.

    Pipeline:
    1. Check circuit breaker — block if OPEN.
    2. Execute the function.
    3. On success → record success, return result.
    4. On failure → classify error.
    5. Adaptive retry loop (with jitter delays).
    6. Recovery graph traversal on persistent failure.
    7. Fallback chain as last resort.
    8. Record all outcomes for learning.
    """

    def __init__(self, config: ResilientConfig) -> None:
        self.config = config
        self.cb = _get_circuit_breaker()
        self.retry = _get_retry_manager()
        self.graph = _get_recovery_graph()
        self.fallback = _get_fallback_chain()
        self.taxonomy = _get_taxonomy()

    async def execute(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute *fn* with the full resilience stack.

        Returns the result of *fn* (or a fallback result).
        Raises the last exception only if all recovery paths fail.
        """
        t0 = time.monotonic()
        outcome = ResilientOutcome(succeeded=False)
        provider = self.config.provider
        model = self.config.model

        # 1. Circuit breaker check
        if self.config.enable_circuit_breaker and provider:
            allowed, reason = await self.cb.check(provider, model, self.config.operation)
            if not allowed:
                logger.warning("Circuit breaker blocked: %s", reason)
                outcome.circuit_breaker_blocked = True
                # Try fallback directly
                if self.config.enable_fallback and self.config.fallback_scenario:
                    return await self._try_fallback(fn, outcome, t0, *args, **kwargs)
                outcome.total_latency_ms = (time.monotonic() - t0) * 1000
                _outcome_log.append(outcome)
                raise RuntimeError(f"Circuit breaker OPEN: {reason}")

        # 2. Execute with retry loop
        last_exc: Optional[Exception] = None
        elapsed_ms = 0.0

        for attempt in range(self.retry.get_policy("", provider).max_attempts + 1):
            outcome.attempts = attempt + 1
            try:
                result = await fn(*args, **kwargs)

                # Success
                if provider:
                    latency = (time.monotonic() - t0) * 1000
                    await self.cb.record_success(provider, model, latency)
                outcome.succeeded = True
                outcome.total_latency_ms = (time.monotonic() - t0) * 1000
                _outcome_log.append(outcome)
                return result

            except Exception as exc:
                last_exc = exc
                elapsed_ms = (time.monotonic() - t0) * 1000

                # Classify error
                error_spec = self.taxonomy.classify_exception(exc)
                outcome.error_code = error_spec.code
                outcome.error_message = str(exc)

                if provider:
                    await self.cb.record_failure(provider, model, error_spec.code, elapsed_ms)

                # Check if retryable
                if not self.config.enable_retry or not error_spec.is_retryable:
                    break

                decision = self.retry.should_retry(
                    attempt=attempt,
                    error_type=error_spec.code,
                    provider=provider,
                    elapsed_ms=elapsed_ms,
                )
                if not decision.should_retry:
                    logger.info("Retry manager says stop: %s", decision.reason)
                    break

                outcome.retry_count += 1
                logger.info(
                    "Retrying (attempt %d, delay %.0fms): %s",
                    attempt + 1, decision.delay_ms, decision.reason,
                )
                await asyncio.sleep(decision.delay_ms / 1000.0)

                # Record retry outcome (unsuccessful so far)
                self.retry.record_retry_outcome(
                    error_type=error_spec.code,
                    provider=provider,
                    attempt=attempt,
                    succeeded=False,
                    delay_ms=decision.delay_ms,
                )

        # 3. Recovery graph
        if self.config.enable_recovery_graph and last_exc is not None:
            error_spec = self.taxonomy.classify_exception(last_exc)
            path = self.graph.traverse(error_spec.code)
            logger.info("Recovery path for %s: %s", error_spec.code, path.nodes)
            # We don't have real handlers registered, but record the path
            outcome.recovery_used = ",".join(path.nodes[:3]) if path.nodes else ""

        # 4. Fallback chain
        if self.config.enable_fallback and self.config.fallback_scenario and last_exc is not None:
            try:
                return await self._try_fallback(fn, outcome, t0, *args, **kwargs)
            except Exception:
                pass

        # All recovery failed
        outcome.total_latency_ms = (time.monotonic() - t0) * 1000
        _outcome_log.append(outcome)

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("Resilient call failed with no exception captured")

    async def _try_fallback(
        self,
        fn: Callable[..., Coroutine[Any, Any, Any]],
        outcome: ResilientOutcome,
        t0: float,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Attempt the fallback chain."""
        scenario = self.config.fallback_scenario
        if scenario is None:
            raise RuntimeError("No fallback scenario configured")

        chain = self.fallback.get_chain(scenario)
        for idx, target in enumerate(chain):
            try:
                # Inject fallback target info into kwargs if possible
                fb_kwargs = dict(kwargs)
                fb_kwargs["_fallback_provider"] = target.provider
                fb_kwargs["_fallback_model"] = target.model

                result = await fn(*args, **fb_kwargs)
                outcome.succeeded = True
                outcome.fallback_used = True
                outcome.fallback_position = idx
                outcome.total_latency_ms = (time.monotonic() - t0) * 1000
                _outcome_log.append(outcome)
                return result
            except Exception as exc:
                logger.warning("Fallback target %s failed: %s", target.name, exc)

        outcome.total_latency_ms = (time.monotonic() - t0) * 1000
        _outcome_log.append(outcome)
        raise RuntimeError(f"All fallback targets exhausted for {scenario.value}")


# ---------------------------------------------------------------------------
# @resilient decorator
# ---------------------------------------------------------------------------

def resilient(
    circuit_breaker: str = "",
    retry_policy: str = "",
    fallback: str = "",
    provider: str = "",
    model: str = "",
    operation: str = "chat",
    enable_circuit_breaker: bool = True,
    enable_retry: bool = True,
    enable_recovery_graph: bool = True,
    enable_fallback: bool = True,
) -> Callable[[F], F]:
    """Decorator that wraps an async function with the full resilience stack.

    Args:
        circuit_breaker: Provider name for circuit breaker (or use *provider*).
        retry_policy: Error-type hint for retry policy selection.
        fallback: Fallback scenario name (e.g. ``"kimi_down"``).
        provider: Provider name for tracking.
        model: Model name for tracking.
        operation: Operation label.
        enable_circuit_breaker: Enable/disable circuit breaker.
        enable_retry: Enable/disable adaptive retry.
        enable_recovery_graph: Enable/disable recovery graph.
        enable_fallback: Enable/disable fallback chain.

    Usage::

        @resilient(provider="moonshot", model="kimi-k2.5", fallback="KIMI_PRIMARY_DOWN")
        async def call_model(prompt: str) -> str:
            ...
    """
    # Resolve fallback scenario
    fallback_scenario: Optional[FallbackScenario] = None
    if fallback:
        fallback_upper = fallback.upper().replace(" ", "_")
        try:
            fallback_scenario = FallbackScenario(fallback_upper)
        except ValueError:
            # Try common aliases
            aliases = {
                "KIMI_DOWN": FallbackScenario.KIMI_PRIMARY_DOWN,
                "KIMI": FallbackScenario.KIMI_PRIMARY_DOWN,
                "SONAR": FallbackScenario.SONAR_DOWN,
                "OUTAGE": FallbackScenario.FULL_OUTAGE,
                "LOAD": FallbackScenario.HIGH_LOAD,
                "RATE": FallbackScenario.RATE_LIMIT,
            }
            fallback_scenario = aliases.get(fallback_upper)

    config = ResilientConfig(
        provider=provider or circuit_breaker,
        model=model,
        fallback_scenario=fallback_scenario,
        enable_circuit_breaker=enable_circuit_breaker,
        enable_retry=enable_retry,
        enable_recovery_graph=enable_recovery_graph,
        enable_fallback=enable_fallback,
        operation=operation,
    )

    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            call = ResilientCall(config)
            return await call.execute(fn, *args, **kwargs)
        return wrapper  # type: ignore[return-value]

    return decorator


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def get_outcome_log() -> list[ResilientOutcome]:
    """Return all recorded resilient call outcomes."""
    return list(_outcome_log)


def clear_outcome_log() -> None:
    """Clear the outcome log."""
    _outcome_log.clear()


def configure_resilience(
    circuit_breaker: Optional[CircuitBreaker] = None,
    retry_manager: Optional[AdaptiveRetryManager] = None,
    recovery_graph: Optional[RecoveryGraph] = None,
    fallback_chain: Optional[FallbackChain] = None,
) -> None:
    """Override the global singleton instances used by :func:`resilient`.

    Useful for testing or custom configuration.
    """
    global _circuit_breaker, _retry_manager, _recovery_graph, _fallback_chain
    if circuit_breaker is not None:
        _circuit_breaker = circuit_breaker
    if retry_manager is not None:
        _retry_manager = retry_manager
    if recovery_graph is not None:
        _recovery_graph = recovery_graph
    if fallback_chain is not None:
        _fallback_chain = fallback_chain
