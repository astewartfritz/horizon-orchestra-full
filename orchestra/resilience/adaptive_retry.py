"""
adaptive_retry.py — Learned, adaptive retry engine for Horizon Orchestra.

Smarter than exponential backoff: uses per-error, per-provider learned
retry timing based on real observed recovery patterns.  Supports
decorrelated jitter (AWS-style), full jitter, and equal jitter.

Key features:
- Per-(error_type, provider) learned policies converge on real recovery times.
- Decorrelated jitter for optimal spread across concurrent retriers.
- Export / load learned policies for persistence across restarts.
"""
from __future__ import annotations

__all__ = [
    "JitterStrategy",
    "RetryPolicy",
    "RetryDecision",
    "AdaptiveRetryManager",
]

import logging
import math
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Jitter strategies
# ---------------------------------------------------------------------------

class JitterStrategy(str, Enum):
    """Jitter algorithm for retry delay calculation."""
    FULL = "full"               # uniform(0, delay)
    EQUAL = "equal"             # delay/2 + uniform(0, delay/2)
    DECORRELATED = "decorrelated"  # min(max_delay, uniform(base, prev * 3))


# ---------------------------------------------------------------------------
# RetryPolicy
# ---------------------------------------------------------------------------

@dataclass
class RetryPolicy:
    """Configurable retry policy for a specific (error_type, provider) pair.

    Attributes:
        base_delay_ms: Starting delay (learned from history).
        max_delay_ms: Hard ceiling on any single delay.
        jitter: Jitter algorithm to use.
        multiplier: Back-off multiplier (adapts toward observed recovery time).
        max_attempts: Hard cap on attempts.
        budget_ms: Total wall-clock budget for all retries combined.
    """
    base_delay_ms: float = 1000.0
    max_delay_ms: float = 60000.0
    jitter: JitterStrategy = JitterStrategy.DECORRELATED
    multiplier: float = 2.0
    max_attempts: int = 3
    budget_ms: float = 120000.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for persistence."""
        return {
            "base_delay_ms": self.base_delay_ms,
            "max_delay_ms": self.max_delay_ms,
            "jitter": self.jitter.value,
            "multiplier": self.multiplier,
            "max_attempts": self.max_attempts,
            "budget_ms": self.budget_ms,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RetryPolicy":
        """Deserialise from a plain dict."""
        return cls(
            base_delay_ms=d.get("base_delay_ms", 1000.0),
            max_delay_ms=d.get("max_delay_ms", 60000.0),
            jitter=JitterStrategy(d.get("jitter", "decorrelated")),
            multiplier=d.get("multiplier", 2.0),
            max_attempts=d.get("max_attempts", 3),
            budget_ms=d.get("budget_ms", 120000.0),
        )


# ---------------------------------------------------------------------------
# Retry decision
# ---------------------------------------------------------------------------

@dataclass
class RetryDecision:
    """Result of :meth:`AdaptiveRetryManager.should_retry`."""
    should_retry: bool
    delay_ms: float = 0.0
    reason: str = ""


# ---------------------------------------------------------------------------
# Internal: outcome history for learning
# ---------------------------------------------------------------------------

@dataclass
class _OutcomeRecord:
    attempt: int
    delay_ms: float
    succeeded: bool
    timestamp: float = field(default_factory=time.monotonic)


# ---------------------------------------------------------------------------
# Seed policies for common error types
# ---------------------------------------------------------------------------

_SEED_POLICIES: dict[str, RetryPolicy] = {
    # Rate limits: typically clear in 1–60 s
    "MODEL_RATE_LIMIT_SOFT": RetryPolicy(
        base_delay_ms=5000, max_delay_ms=60000, jitter=JitterStrategy.DECORRELATED,
        multiplier=2.0, max_attempts=5, budget_ms=120000,
    ),
    "MODEL_RATE_LIMIT_HARD": RetryPolicy(
        base_delay_ms=10000, max_delay_ms=60000, jitter=JitterStrategy.FULL,
        multiplier=2.5, max_attempts=3, budget_ms=60000,
    ),
    # Timeouts: server recovers in 200–500 ms
    "NETWORK_TIMEOUT_CONNECT": RetryPolicy(
        base_delay_ms=250, max_delay_ms=5000, jitter=JitterStrategy.DECORRELATED,
        multiplier=2.0, max_attempts=4, budget_ms=15000,
    ),
    "NETWORK_TIMEOUT_READ": RetryPolicy(
        base_delay_ms=300, max_delay_ms=8000, jitter=JitterStrategy.DECORRELATED,
        multiplier=2.0, max_attempts=4, budget_ms=20000,
    ),
    "NETWORK_TIMEOUT_WRITE": RetryPolicy(
        base_delay_ms=250, max_delay_ms=5000, jitter=JitterStrategy.EQUAL,
        multiplier=2.0, max_attempts=3, budget_ms=10000,
    ),
    # 503 / overloaded: 10–30 s recovery
    "MODEL_OVERLOADED": RetryPolicy(
        base_delay_ms=15000, max_delay_ms=60000, jitter=JitterStrategy.DECORRELATED,
        multiplier=1.5, max_attempts=3, budget_ms=90000,
    ),
    "MODEL_UNAVAILABLE": RetryPolicy(
        base_delay_ms=10000, max_delay_ms=60000, jitter=JitterStrategy.FULL,
        multiplier=2.0, max_attempts=3, budget_ms=60000,
    ),
    # Content errors: fast retry
    "CONTENT_EMPTY_RESPONSE": RetryPolicy(
        base_delay_ms=500, max_delay_ms=5000, jitter=JitterStrategy.FULL,
        multiplier=1.5, max_attempts=3, budget_ms=15000,
    ),
    "CONTENT_MALFORMED_JSON": RetryPolicy(
        base_delay_ms=500, max_delay_ms=5000, jitter=JitterStrategy.EQUAL,
        multiplier=1.5, max_attempts=3, budget_ms=15000,
    ),
    # Streaming: reconnect quickly
    "STREAMING_SSE_DISCONNECTED": RetryPolicy(
        base_delay_ms=200, max_delay_ms=5000, jitter=JitterStrategy.DECORRELATED,
        multiplier=2.0, max_attempts=5, budget_ms=15000,
    ),
    # Network errors
    "NETWORK_CONNECTION_REFUSED": RetryPolicy(
        base_delay_ms=1000, max_delay_ms=15000, jitter=JitterStrategy.DECORRELATED,
        multiplier=2.0, max_attempts=3, budget_ms=30000,
    ),
    "NETWORK_HOST_UNREACHABLE": RetryPolicy(
        base_delay_ms=2000, max_delay_ms=20000, jitter=JitterStrategy.FULL,
        multiplier=2.0, max_attempts=3, budget_ms=30000,
    ),
    # Execution
    "EXECUTION_TOOL_TIMEOUT": RetryPolicy(
        base_delay_ms=1000, max_delay_ms=30000, jitter=JitterStrategy.DECORRELATED,
        multiplier=2.0, max_attempts=3, budget_ms=60000,
    ),
    "EXECUTION_SANDBOX_CRASH": RetryPolicy(
        base_delay_ms=2000, max_delay_ms=15000, jitter=JitterStrategy.EQUAL,
        multiplier=2.0, max_attempts=2, budget_ms=30000,
    ),
}

# Default policy for unregistered error types
_FALLBACK_POLICY = RetryPolicy(
    base_delay_ms=1000, max_delay_ms=30000, jitter=JitterStrategy.DECORRELATED,
    multiplier=2.0, max_attempts=3, budget_ms=60000,
)


# ---------------------------------------------------------------------------
# AdaptiveRetryManager
# ---------------------------------------------------------------------------

class AdaptiveRetryManager:
    """Manages learned retry policies and makes retry decisions.

    Each ``(error_type, provider)`` pair has its own :class:`RetryPolicy`
    whose ``base_delay_ms`` and ``multiplier`` converge over time toward
    the real observed recovery durations.

    Example::

        mgr = AdaptiveRetryManager()
        policy = mgr.get_policy("MODEL_RATE_LIMIT_SOFT", "moonshot")
        decision = mgr.should_retry(attempt=1, error_type="MODEL_RATE_LIMIT_SOFT",
                                     provider="moonshot", elapsed_ms=2000)
        if decision.should_retry:
            await asyncio.sleep(decision.delay_ms / 1000)
    """

    def __init__(self) -> None:
        # (error_type, provider) → learned policy
        self._policies: dict[tuple[str, str], RetryPolicy] = {}
        # (error_type, provider) → history of outcomes
        self._history: dict[tuple[str, str], list[_OutcomeRecord]] = {}
        # Track last decorrelated delay for each key
        self._last_decorrelated: dict[tuple[str, str], float] = {}

    # -- public API -------------------------------------------------------

    def get_policy(self, error_type: str, provider: str = "") -> RetryPolicy:
        """Return the current retry policy for *(error_type, provider)*.

        If no learned policy exists, falls back to seed policies or
        the global default.
        """
        key = (error_type, provider)
        if key in self._policies:
            return self._policies[key]
        # Try error-only key
        if (error_type, "") in self._policies:
            return self._policies[(error_type, "")]
        # Seed policy
        if error_type in _SEED_POLICIES:
            policy = RetryPolicy.from_dict(_SEED_POLICIES[error_type].to_dict())  # copy
            self._policies[key] = policy
            return policy
        # Global fallback
        policy = RetryPolicy.from_dict(_FALLBACK_POLICY.to_dict())
        self._policies[key] = policy
        return policy

    def should_retry(
        self,
        attempt: int,
        error_type: str,
        provider: str = "",
        elapsed_ms: float = 0.0,
    ) -> RetryDecision:
        """Decide whether to retry and how long to wait.

        Args:
            attempt: Zero-based attempt number (0 = first retry).
            error_type: Error code from the taxonomy.
            provider: Provider identifier.
            elapsed_ms: Total time already spent retrying.

        Returns:
            A :class:`RetryDecision`.
        """
        policy = self.get_policy(error_type, provider)

        # Budget exceeded?
        if elapsed_ms >= policy.budget_ms:
            return RetryDecision(
                should_retry=False, delay_ms=0,
                reason=f"Budget exhausted ({elapsed_ms:.0f}ms >= {policy.budget_ms:.0f}ms)",
            )

        # Max attempts exceeded?
        if attempt >= policy.max_attempts:
            return RetryDecision(
                should_retry=False, delay_ms=0,
                reason=f"Max attempts reached ({attempt} >= {policy.max_attempts})",
            )

        # Compute delay
        delay = self._compute_delay(attempt, policy, error_type, provider)

        # Ensure we don't exceed remaining budget
        remaining = policy.budget_ms - elapsed_ms
        if delay > remaining:
            if remaining > 0:
                delay = remaining
            else:
                return RetryDecision(
                    should_retry=False, delay_ms=0,
                    reason="Remaining budget too small for another retry",
                )

        return RetryDecision(
            should_retry=True,
            delay_ms=round(delay, 1),
            reason=f"Retry #{attempt + 1} with {delay:.0f}ms delay ({policy.jitter.value} jitter)",
        )

    def record_retry_outcome(
        self,
        error_type: str,
        provider: str,
        attempt: int,
        succeeded: bool,
        delay_ms: float,
    ) -> None:
        """Record a retry outcome to update learned policies.

        Over time this converges ``base_delay_ms`` toward the real
        recovery duration observed in production.
        """
        key = (error_type, provider)
        if key not in self._history:
            self._history[key] = []
        self._history[key].append(
            _OutcomeRecord(attempt=attempt, delay_ms=delay_ms, succeeded=succeeded)
        )

        # Keep last 200 observations
        if len(self._history[key]) > 200:
            self._history[key] = self._history[key][-200:]

        # Update policy based on observations
        self._learn(key)

    def export_learned_policies(self) -> dict[str, Any]:
        """Export all learned policies for persistence.

        Returns a JSON-serialisable dict keyed by ``"error_type::provider"``.
        """
        data: dict[str, Any] = {}
        for (etype, prov), policy in self._policies.items():
            pkey = f"{etype}::{prov}" if prov else etype
            data[pkey] = policy.to_dict()
        return data

    def load_policies(self, data: dict[str, Any]) -> None:
        """Load previously exported policies.

        Args:
            data: Dict from :meth:`export_learned_policies`.
        """
        for pkey, pdict in data.items():
            if "::" in pkey:
                etype, prov = pkey.split("::", 1)
            else:
                etype, prov = pkey, ""
            self._policies[(etype, prov)] = RetryPolicy.from_dict(pdict)
        logger.info("Loaded %d retry policies", len(data))

    # -- internal ---------------------------------------------------------

    def _compute_delay(
        self,
        attempt: int,
        policy: RetryPolicy,
        error_type: str,
        provider: str,
    ) -> float:
        """Compute the next retry delay using the configured jitter strategy."""
        base = policy.base_delay_ms
        cap = policy.max_delay_ms

        if policy.jitter == JitterStrategy.DECORRELATED:
            # AWS-recommended decorrelated jitter
            key = (error_type, provider)
            prev = self._last_decorrelated.get(key, base)
            delay = min(cap, random.uniform(base, prev * 3))
            self._last_decorrelated[key] = delay
            return delay

        # Standard exponential backoff
        exp_delay = base * (policy.multiplier ** attempt)
        capped = min(exp_delay, cap)

        if policy.jitter == JitterStrategy.FULL:
            return random.uniform(0, capped)
        elif policy.jitter == JitterStrategy.EQUAL:
            half = capped / 2
            return half + random.uniform(0, half)
        else:
            return capped

    def _learn(self, key: tuple[str, str]) -> None:
        """Update policy parameters from observed outcomes.

        Uses exponential moving average on successful recovery delays
        to converge ``base_delay_ms`` toward real recovery times.
        Also adjusts ``multiplier`` if retries consistently succeed/fail
        at specific attempts.
        """
        history = self._history.get(key, [])
        if len(history) < 5:
            return  # Not enough data

        policy = self._policies.get(key)
        if policy is None:
            return

        # EMA of delays on successful outcomes
        alpha = 0.15
        successes = [r for r in history[-50:] if r.succeeded]
        if successes:
            avg_success_delay = sum(r.delay_ms for r in successes) / len(successes)
            # Move base_delay toward what actually works
            new_base = (1 - alpha) * policy.base_delay_ms + alpha * avg_success_delay
            # Clamp to reasonable range
            new_base = max(50.0, min(new_base, policy.max_delay_ms / 2))

            # Adjust multiplier: if high-attempt retries succeed often,
            # the multiplier is probably too aggressive
            late_successes = [r for r in successes if r.attempt >= 2]
            early_successes = [r for r in successes if r.attempt < 2]
            if len(late_successes) > len(early_successes) and policy.multiplier > 1.2:
                new_mult = policy.multiplier * 0.95  # reduce aggressiveness
            else:
                new_mult = policy.multiplier

            # Mutate policy (dataclass is mutable, not frozen)
            object.__setattr__(policy, "base_delay_ms", round(new_base, 1))
            object.__setattr__(policy, "multiplier", round(new_mult, 3))

        # Adjust max_attempts if we consistently exhaust them
        failures = [r for r in history[-20:] if not r.succeeded]
        if len(failures) >= 15 and policy.max_attempts < 6:
            object.__setattr__(policy, "max_attempts", policy.max_attempts + 1)
            logger.info("Increased max_attempts for %s to %d", key, policy.max_attempts)
