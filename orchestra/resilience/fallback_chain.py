"""
fallback_chain.py — Zero-downtime fallback chains for Horizon Orchestra.

Pre-configured chains for every major failure scenario across the full
model / provider matrix.  Each chain defines an ordered list of
:class:`FallbackTarget` entries with degradation estimates.
"""
from __future__ import annotations

__all__ = [
    "FallbackScenario",
    "FallbackTarget",
    "FallbackResult",
    "DegradationEstimate",
    "FallbackChain",
]

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class FallbackScenario(str, Enum):
    """Named failure scenarios with pre-built chains."""
    KIMI_PRIMARY_DOWN = "KIMI_PRIMARY_DOWN"
    SONAR_DOWN = "SONAR_DOWN"
    FULL_OUTAGE = "FULL_OUTAGE"
    HIGH_LOAD = "HIGH_LOAD"
    RATE_LIMIT = "RATE_LIMIT"


@dataclass
class FallbackTarget:
    """A single target in a fallback chain.

    Attributes:
        name: Human-readable label (e.g. ``"Kimi K2.5 via OpenRouter"``).
        provider: Provider identifier.
        model: Model identifier.
        priority: Lower = tried first.
        quality_score: 0.0–1.0 estimated quality relative to primary.
        latency_estimate_ms: Expected p50 latency.
        is_available: Whether a quick health check passed.
        health_check_fn: Optional async callable returning ``bool``.
    """
    name: str
    provider: str
    model: str
    priority: int = 0
    quality_score: float = 1.0
    latency_estimate_ms: float = 500.0
    is_available: bool = True
    health_check_fn: Optional[Callable[..., Coroutine[Any, Any, bool]]] = None


@dataclass
class FallbackResult:
    """Outcome of executing a fallback chain."""
    succeeded: bool
    target_used: Optional[FallbackTarget] = None
    attempts: int = 0
    total_latency_ms: float = 0.0
    data: Any = None
    error: str = ""
    chain_position: int = 0  # 0-based position in chain where success occurred


@dataclass
class DegradationEstimate:
    """Estimate of quality degradation at a given chain position.

    Attributes:
        position: 0-based position in the chain.
        target_name: Which target is being used.
        quality_score: Estimated quality (0.0–1.0) relative to primary.
        latency_increase_pct: Expected latency increase as a percentage.
        features_lost: List of features unavailable at this position.
        user_impact: Human-readable description of impact.
    """
    position: int
    target_name: str
    quality_score: float
    latency_increase_pct: float
    features_lost: list[str] = field(default_factory=list)
    user_impact: str = ""


# ---------------------------------------------------------------------------
# Pre-configured chains
# ---------------------------------------------------------------------------

_KIMI_PRIMARY_DOWN: list[FallbackTarget] = [
    FallbackTarget(
        name="Kimi K2.5 via OpenRouter",
        provider="openrouter", model="moonshotai/kimi-k2.5",
        priority=1, quality_score=0.98, latency_estimate_ms=600,
    ),
    FallbackTarget(
        name="Kimi K2.5 via Together",
        provider="together", model="moonshotai/Kimi-K2.5",
        priority=2, quality_score=0.97, latency_estimate_ms=700,
    ),
    FallbackTarget(
        name="Claude Opus 4.6",
        provider="anthropic", model="claude-opus-4.6",
        priority=3, quality_score=0.92, latency_estimate_ms=800,
    ),
    FallbackTarget(
        name="GPT-5.4",
        provider="openai", model="gpt-5.4",
        priority=4, quality_score=0.90, latency_estimate_ms=700,
    ),
    FallbackTarget(
        name="Gemma 4 31B",
        provider="local", model="gemma-4-31b",
        priority=5, quality_score=0.75, latency_estimate_ms=1200,
    ),
]

_SONAR_DOWN: list[FallbackTarget] = [
    FallbackTarget(
        name="Sonar Pro",
        provider="perplexity", model="sonar-pro",
        priority=1, quality_score=1.0, latency_estimate_ms=800,
    ),
    FallbackTarget(
        name="Sonar",
        provider="perplexity", model="sonar",
        priority=2, quality_score=0.85, latency_estimate_ms=500,
    ),
    FallbackTarget(
        name="Gemma 4 12B + web_search",
        provider="local", model="gemma-4-12b",
        priority=3, quality_score=0.60, latency_estimate_ms=1500,
    ),
]

_FULL_OUTAGE: list[FallbackTarget] = [
    FallbackTarget(
        name="Cached Responses",
        provider="cache", model="cached",
        priority=1, quality_score=0.50, latency_estimate_ms=10,
    ),
    FallbackTarget(
        name="Local vLLM",
        provider="local", model="vllm-local",
        priority=2, quality_score=0.40, latency_estimate_ms=2000,
    ),
    FallbackTarget(
        name="Degraded Mode",
        provider="degraded", model="degraded",
        priority=3, quality_score=0.10, latency_estimate_ms=5,
    ),
]

_HIGH_LOAD: list[FallbackTarget] = [
    FallbackTarget(
        name="Primary Model",
        provider="moonshot", model="kimi-k2.5",
        priority=1, quality_score=1.0, latency_estimate_ms=500,
    ),
    FallbackTarget(
        name="Spot GPU Scale-Out",
        provider="spot", model="kimi-k2.5-spot",
        priority=2, quality_score=0.95, latency_estimate_ms=1000,
    ),
    FallbackTarget(
        name="Request Queue",
        provider="queue", model="queued",
        priority=3, quality_score=0.90, latency_estimate_ms=5000,
    ),
]

_RATE_LIMIT: list[FallbackTarget] = [
    FallbackTarget(
        name="Rotate API Key",
        provider="moonshot", model="kimi-k2.5",
        priority=1, quality_score=1.0, latency_estimate_ms=100,
    ),
    FallbackTarget(
        name="Switch Provider (OpenRouter)",
        provider="openrouter", model="moonshotai/kimi-k2.5",
        priority=2, quality_score=0.98, latency_estimate_ms=600,
    ),
    FallbackTarget(
        name="Switch Provider (Together)",
        provider="together", model="moonshotai/Kimi-K2.5",
        priority=3, quality_score=0.97, latency_estimate_ms=700,
    ),
    FallbackTarget(
        name="Queue with Notification",
        provider="queue", model="queued-notify",
        priority=4, quality_score=0.90, latency_estimate_ms=10000,
    ),
]

_CHAINS: dict[FallbackScenario, list[FallbackTarget]] = {
    FallbackScenario.KIMI_PRIMARY_DOWN: _KIMI_PRIMARY_DOWN,
    FallbackScenario.SONAR_DOWN: _SONAR_DOWN,
    FallbackScenario.FULL_OUTAGE: _FULL_OUTAGE,
    FallbackScenario.HIGH_LOAD: _HIGH_LOAD,
    FallbackScenario.RATE_LIMIT: _RATE_LIMIT,
}


# ---------------------------------------------------------------------------
# FallbackChain
# ---------------------------------------------------------------------------

class FallbackChain:
    """Zero-downtime fallback chain manager.

    Maintains pre-configured chains for named scenarios and provides
    methods to execute chains, test health, and estimate degradation.

    Example::

        chain = FallbackChain()
        targets = chain.get_chain(FallbackScenario.KIMI_PRIMARY_DOWN)
        health = await chain.test_chain_health()
    """

    def __init__(
        self,
        chains: Optional[dict[FallbackScenario, list[FallbackTarget]]] = None,
    ) -> None:
        self._chains: dict[FallbackScenario, list[FallbackTarget]] = {}
        for scenario, targets in (chains or _CHAINS).items():
            self._chains[scenario] = sorted(targets, key=lambda t: t.priority)

    # -- chain access -----------------------------------------------------

    def get_chain(self, scenario: FallbackScenario) -> list[FallbackTarget]:
        """Return the ordered fallback targets for *scenario*."""
        return list(self._chains.get(scenario, []))

    def add_target(self, scenario: FallbackScenario, target: FallbackTarget) -> None:
        """Append a target to the chain for *scenario*."""
        if scenario not in self._chains:
            self._chains[scenario] = []
        self._chains[scenario].append(target)
        self._chains[scenario].sort(key=lambda t: t.priority)

    # -- execution --------------------------------------------------------

    async def try_chain(
        self,
        request: dict[str, Any],
        scenario: FallbackScenario,
        execute_fn: Optional[Callable[..., Coroutine[Any, Any, Any]]] = None,
    ) -> FallbackResult:
        """Try each target in the chain until one succeeds.

        Args:
            request: The request payload.
            scenario: Which fallback chain to use.
            execute_fn: Async callable ``(target, request) → result``
                        that attempts the request against a target.
                        If ``None``, returns the first available target
                        as a dry-run result.

        Returns:
            A :class:`FallbackResult`.
        """
        chain = self.get_chain(scenario)
        if not chain:
            return FallbackResult(
                succeeded=False, error=f"No chain configured for {scenario.value}"
            )

        t0 = time.monotonic()
        attempts = 0

        for idx, target in enumerate(chain):
            attempts += 1

            # Quick availability check
            if target.health_check_fn is not None:
                try:
                    available = await asyncio.wait_for(target.health_check_fn(), timeout=2.0)
                    if not available:
                        logger.info("Fallback target %s unavailable — skipping", target.name)
                        continue
                except (asyncio.TimeoutError, Exception):
                    logger.warning("Health check failed for %s — skipping", target.name)
                    continue

            if execute_fn is None:
                # Dry run — return first available
                return FallbackResult(
                    succeeded=True,
                    target_used=target,
                    attempts=attempts,
                    total_latency_ms=(time.monotonic() - t0) * 1000,
                    chain_position=idx,
                )

            try:
                result = await execute_fn(target, request)
                return FallbackResult(
                    succeeded=True,
                    target_used=target,
                    attempts=attempts,
                    total_latency_ms=(time.monotonic() - t0) * 1000,
                    data=result,
                    chain_position=idx,
                )
            except Exception as exc:
                logger.warning("Fallback target %s failed: %s", target.name, exc)

        return FallbackResult(
            succeeded=False,
            attempts=attempts,
            total_latency_ms=(time.monotonic() - t0) * 1000,
            error=f"All {attempts} targets in chain {scenario.value} failed",
        )

    # -- health testing ---------------------------------------------------

    async def test_chain_health(self) -> dict[str, dict[str, Any]]:
        """Test health of all chains.

        Returns a dict mapping scenario names to their health status::

            {
                "KIMI_PRIMARY_DOWN": {
                    "total_targets": 5,
                    "available_targets": 4,
                    "first_available": "Kimi K2.5 via OpenRouter",
                    "healthy": True,
                },
                ...
            }
        """
        result: dict[str, dict[str, Any]] = {}

        for scenario, chain in self._chains.items():
            total = len(chain)
            available = 0
            first_available: Optional[str] = None

            for target in chain:
                is_avail = True
                if target.health_check_fn is not None:
                    try:
                        is_avail = await asyncio.wait_for(target.health_check_fn(), timeout=2.0)
                    except (asyncio.TimeoutError, Exception):
                        is_avail = False

                target.is_available = is_avail
                if is_avail:
                    available += 1
                    if first_available is None:
                        first_available = target.name

            result[scenario.value] = {
                "total_targets": total,
                "available_targets": available,
                "first_available": first_available,
                "healthy": available > 0,
            }

        return result

    # -- degradation estimation -------------------------------------------

    def estimate_degradation(self, chain_position: int, scenario: Optional[FallbackScenario] = None) -> DegradationEstimate:
        """Estimate quality degradation at a given chain position.

        Args:
            chain_position: 0-based index into the chain.
            scenario: Which chain to evaluate. Defaults to
                      ``KIMI_PRIMARY_DOWN``.

        Returns:
            A :class:`DegradationEstimate`.
        """
        sc = scenario or FallbackScenario.KIMI_PRIMARY_DOWN
        chain = self.get_chain(sc)

        if not chain or chain_position >= len(chain):
            return DegradationEstimate(
                position=chain_position,
                target_name="none",
                quality_score=0.0,
                latency_increase_pct=999.0,
                features_lost=["all"],
                user_impact="Service unavailable — all fallbacks exhausted.",
            )

        target = chain[chain_position]
        primary = chain[0] if chain else target

        latency_increase = 0.0
        if primary.latency_estimate_ms > 0:
            latency_increase = (
                (target.latency_estimate_ms - primary.latency_estimate_ms)
                / primary.latency_estimate_ms * 100
            )

        features_lost: list[str] = []
        if target.quality_score < 0.9:
            features_lost.append("reduced_reasoning_depth")
        if target.quality_score < 0.7:
            features_lost.append("limited_tool_use")
        if target.quality_score < 0.5:
            features_lost.append("no_streaming")
            features_lost.append("cached_responses_only")
        if target.quality_score < 0.2:
            features_lost.append("minimal_response_quality")

        if target.quality_score >= 0.95:
            impact = "Minimal impact — near-primary quality."
        elif target.quality_score >= 0.85:
            impact = "Slight quality reduction; all features available."
        elif target.quality_score >= 0.7:
            impact = "Noticeable quality reduction; some advanced features limited."
        elif target.quality_score >= 0.4:
            impact = "Significant degradation; basic functionality only."
        else:
            impact = "Emergency mode; minimal functionality available."

        return DegradationEstimate(
            position=chain_position,
            target_name=target.name,
            quality_score=target.quality_score,
            latency_increase_pct=round(latency_increase, 1),
            features_lost=features_lost,
            user_impact=impact,
        )
