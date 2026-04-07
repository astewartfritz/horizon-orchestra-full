"""
circuit_breaker.py — Three-tier circuit breaker for Horizon Orchestra.

Implements per-request, per-provider, and system-level circuit breakers
with adaptive thresholds that adjust based on time-of-day traffic patterns.
All state mutations are guarded by ``asyncio.Lock`` for concurrency safety.

States: CLOSED → HALF_OPEN → OPEN → (reset) → CLOSED
"""
from __future__ import annotations

__all__ = [
    "CircuitState",
    "AdaptiveThreshold",
    "BreakerLevel",
    "CircuitBreaker",
]

import asyncio
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums & value objects
# ---------------------------------------------------------------------------

class CircuitState(str, Enum):
    """Circuit-breaker states."""
    CLOSED = "CLOSED"
    HALF_OPEN = "HALF_OPEN"
    OPEN = "OPEN"


class BreakerLevel(int, Enum):
    """Three-tier breaker hierarchy."""
    REQUEST = 1   # per (provider, model, operation)
    PROVIDER = 2  # per provider aggregate
    SYSTEM = 3    # global emergency brake


@dataclass
class BreakerRecord:
    """Mutable record for one circuit."""
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_success_time: float = 0.0
    last_state_change: float = field(default_factory=time.monotonic)
    half_open_successes: int = 0
    half_open_trials: int = 0
    forced_reason: Optional[str] = None


@dataclass
class HealthSnapshot:
    """Health info for a single (provider, model) pair."""
    provider: str
    model: str
    state: CircuitState
    failure_rate: float
    avg_latency_ms: float
    total_requests: int
    last_failure: Optional[float]


# ---------------------------------------------------------------------------
# Adaptive threshold
# ---------------------------------------------------------------------------

class AdaptiveThreshold:
    """Adjusts circuit trip thresholds based on time-of-day traffic patterns.

    During peak hours (09:00–21:00 UTC) sensitivity is reduced (higher
    threshold) to avoid false trips from normal load spikes.  During
    off-peak or known maintenance windows, sensitivity is increased.

    Attributes:
        base_failure_threshold: Default consecutive failures to trip.
        base_failure_rate: Default failure-rate percentage to trip.
        peak_hours: Tuple of (start_hour, end_hour) in UTC.
        maintenance_windows: List of (start_hour, end_hour) UTC windows.
    """

    def __init__(
        self,
        base_failure_threshold: int = 5,
        base_failure_rate: float = 0.50,
        peak_hours: tuple[int, int] = (9, 21),
        maintenance_windows: Optional[list[tuple[int, int]]] = None,
    ) -> None:
        self.base_failure_threshold = base_failure_threshold
        self.base_failure_rate = base_failure_rate
        self.peak_hours = peak_hours
        self.maintenance_windows = maintenance_windows or []

    def current_failure_threshold(self) -> int:
        """Return adjusted failure count threshold for now."""
        hour = self._current_hour()
        if self._in_maintenance(hour):
            # More sensitive during maintenance
            return max(2, self.base_failure_threshold // 2)
        if self._in_peak(hour):
            # Less sensitive during peak
            return self.base_failure_threshold + 3
        return self.base_failure_threshold

    def current_failure_rate(self) -> float:
        """Return adjusted failure-rate threshold for now."""
        hour = self._current_hour()
        if self._in_maintenance(hour):
            return max(0.20, self.base_failure_rate - 0.15)
        if self._in_peak(hour):
            return min(0.70, self.base_failure_rate + 0.10)
        return self.base_failure_rate

    # -- internals --------------------------------------------------------

    @staticmethod
    def _current_hour() -> int:
        return int(time.strftime("%H", time.gmtime()))

    def _in_peak(self, hour: int) -> bool:
        start, end = self.peak_hours
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end  # wraps midnight

    def _in_maintenance(self, hour: int) -> bool:
        for start, end in self.maintenance_windows:
            if start <= end:
                if start <= hour < end:
                    return True
            else:
                if hour >= start or hour < end:
                    return True
        return False


# ---------------------------------------------------------------------------
# Sliding window for provider-level stats
# ---------------------------------------------------------------------------

@dataclass
class _RequestEvent:
    timestamp: float
    success: bool
    latency_ms: float


class _SlidingWindow:
    """Fixed-duration sliding window of request events."""

    def __init__(self, window_seconds: float = 60.0, max_size: int = 10_000) -> None:
        self._window = window_seconds
        self._max = max_size
        self._events: deque[_RequestEvent] = deque(maxlen=max_size)

    def record(self, success: bool, latency_ms: float) -> None:
        self._events.append(_RequestEvent(time.monotonic(), success, latency_ms))

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._window
        while self._events and self._events[0].timestamp < cutoff:
            self._events.popleft()

    @property
    def total(self) -> int:
        self._prune()
        return len(self._events)

    @property
    def failure_rate(self) -> float:
        self._prune()
        if not self._events:
            return 0.0
        failures = sum(1 for e in self._events if not e.success)
        return failures / len(self._events)

    @property
    def avg_latency_ms(self) -> float:
        self._prune()
        if not self._events:
            return 0.0
        return sum(e.latency_ms for e in self._events) / len(self._events)


# ---------------------------------------------------------------------------
# Main CircuitBreaker
# ---------------------------------------------------------------------------

class CircuitBreaker:
    """Three-tier, adaptive circuit breaker.

    * **Level 1 (request):** trips after *N* consecutive failures for a
      specific ``(provider, model)`` pair.
    * **Level 2 (provider):** trips when failure rate in a sliding window
      exceeds the adaptive threshold.
    * **Level 3 (system):** emergency brake when all tracked providers
      are degraded simultaneously.

    All public methods are coroutine-safe via ``asyncio.Lock``.
    """

    def __init__(
        self,
        threshold: Optional[AdaptiveThreshold] = None,
        open_duration_s: float = 30.0,
        half_open_max_trials: int = 3,
        half_open_success_required: int = 2,
        window_seconds: float = 60.0,
    ) -> None:
        self._threshold = threshold or AdaptiveThreshold()
        self._open_duration = open_duration_s
        self._ho_max_trials = half_open_max_trials
        self._ho_success_needed = half_open_success_required
        self._window_seconds = window_seconds

        # (provider, model) → BreakerRecord
        self._records: dict[tuple[str, str], BreakerRecord] = defaultdict(BreakerRecord)
        # provider → SlidingWindow
        self._provider_windows: dict[str, _SlidingWindow] = defaultdict(
            lambda: _SlidingWindow(window_seconds)
        )
        # global lock
        self._lock = asyncio.Lock()

        # System-level state
        self._system_state = CircuitState.CLOSED
        self._system_forced_reason: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def check(
        self,
        provider: str,
        model: str,
        operation: str = "chat",
    ) -> tuple[bool, str]:
        """Check whether a request to *(provider, model)* is allowed.

        Returns:
            ``(allowed, reason)`` — *reason* is empty when allowed.
        """
        async with self._lock:
            # Level 3: system-level
            if self._system_state == CircuitState.OPEN:
                return False, f"System breaker OPEN: {self._system_forced_reason or 'all providers degraded'}"

            key = (provider, model)
            rec = self._records[key]

            # Check if OPEN breaker should transition to HALF_OPEN
            if rec.state == CircuitState.OPEN:
                elapsed = time.monotonic() - rec.last_state_change
                if elapsed >= self._open_duration:
                    rec.state = CircuitState.HALF_OPEN
                    rec.half_open_successes = 0
                    rec.half_open_trials = 0
                    rec.last_state_change = time.monotonic()
                    logger.info("Circuit %s→HALF_OPEN for %s/%s", CircuitState.OPEN.value, provider, model)
                else:
                    reason = rec.forced_reason or f"Circuit OPEN (resets in {self._open_duration - elapsed:.1f}s)"
                    return False, reason

            # Level 1: request-level check
            if rec.state == CircuitState.CLOSED:
                threshold = self._threshold.current_failure_threshold()
                if rec.failure_count >= threshold:
                    rec.state = CircuitState.OPEN
                    rec.last_state_change = time.monotonic()
                    logger.warning(
                        "Circuit OPEN (L1) for %s/%s: %d consecutive failures (threshold=%d)",
                        provider, model, rec.failure_count, threshold,
                    )
                    return False, f"L1: {rec.failure_count} consecutive failures"

            # Level 2: provider-level check
            win = self._provider_windows[provider]
            rate_threshold = self._threshold.current_failure_rate()
            if win.total >= 10 and win.failure_rate > rate_threshold:
                if rec.state != CircuitState.OPEN:
                    rec.state = CircuitState.OPEN
                    rec.last_state_change = time.monotonic()
                    logger.warning(
                        "Circuit OPEN (L2) for %s/%s: failure_rate=%.2f > %.2f",
                        provider, model, win.failure_rate, rate_threshold,
                    )
                return False, f"L2: provider failure rate {win.failure_rate:.0%} > {rate_threshold:.0%}"

            # HALF_OPEN: allow limited trials
            if rec.state == CircuitState.HALF_OPEN:
                if rec.half_open_trials >= self._ho_max_trials:
                    if rec.half_open_successes < self._ho_success_needed:
                        rec.state = CircuitState.OPEN
                        rec.last_state_change = time.monotonic()
                        return False, "HALF_OPEN trials exhausted without enough successes"
                    else:
                        # Enough successes — close
                        rec.state = CircuitState.CLOSED
                        rec.failure_count = 0
                        rec.last_state_change = time.monotonic()
                        logger.info("Circuit CLOSED for %s/%s (HALF_OPEN passed)", provider, model)

            return True, ""

    async def record_success(
        self, provider: str, model: str, latency_ms: float
    ) -> None:
        """Record a successful request."""
        async with self._lock:
            key = (provider, model)
            rec = self._records[key]
            rec.failure_count = 0
            rec.success_count += 1
            rec.last_success_time = time.monotonic()
            rec.forced_reason = None

            if rec.state == CircuitState.HALF_OPEN:
                rec.half_open_successes += 1
                rec.half_open_trials += 1
                if rec.half_open_successes >= self._ho_success_needed:
                    rec.state = CircuitState.CLOSED
                    rec.last_state_change = time.monotonic()
                    logger.info("Circuit CLOSED for %s/%s (recovery confirmed)", provider, model)

            self._provider_windows[provider].record(True, latency_ms)
            self._check_system_recovery()

    async def record_failure(
        self,
        provider: str,
        model: str,
        error_type: str,
        latency_ms: float,
    ) -> None:
        """Record a failed request."""
        async with self._lock:
            key = (provider, model)
            rec = self._records[key]
            rec.failure_count += 1
            rec.last_failure_time = time.monotonic()

            if rec.state == CircuitState.HALF_OPEN:
                rec.half_open_trials += 1
                if rec.half_open_trials >= self._ho_max_trials:
                    if rec.half_open_successes < self._ho_success_needed:
                        rec.state = CircuitState.OPEN
                        rec.last_state_change = time.monotonic()
                        logger.warning("Circuit re-OPEN for %s/%s (HALF_OPEN failed)", provider, model)

            self._provider_windows[provider].record(False, latency_ms)
            self._check_system_level()

    async def get_state(self, provider: str, model: str) -> CircuitState:
        """Return the current state for *(provider, model)*."""
        async with self._lock:
            return self._records[(provider, model)].state

    async def force_open(self, provider: str, reason: str) -> None:
        """Emergency: force-open all circuits for *provider*."""
        async with self._lock:
            for (p, m), rec in self._records.items():
                if p == provider:
                    rec.state = CircuitState.OPEN
                    rec.last_state_change = time.monotonic()
                    rec.forced_reason = reason
            logger.critical("FORCE OPEN all circuits for provider=%s reason=%s", provider, reason)

    async def force_close(self, provider: str) -> None:
        """Manual recovery: force-close all circuits for *provider*."""
        async with self._lock:
            for (p, m), rec in self._records.items():
                if p == provider:
                    rec.state = CircuitState.CLOSED
                    rec.failure_count = 0
                    rec.forced_reason = None
                    rec.last_state_change = time.monotonic()
            logger.info("FORCE CLOSE all circuits for provider=%s", provider)

    async def get_health_matrix(self) -> dict[str, Any]:
        """Return a full provider × model × state health grid.

        Returns a dict structured as::

            {
                "system_state": "CLOSED",
                "providers": {
                    "moonshot": {
                        "kimi-k2.5": {"state": "CLOSED", "failure_rate": 0.02, ...},
                        ...
                    }
                },
                "summary": {"healthy": 5, "degraded": 1, "down": 0}
            }
        """
        async with self._lock:
            providers: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
            healthy = degraded = down = 0

            for (prov, mdl), rec in self._records.items():
                win = self._provider_windows.get(prov)
                frate = win.failure_rate if win else 0.0
                avg_lat = win.avg_latency_ms if win else 0.0
                total = win.total if win else 0

                entry: dict[str, Any] = {
                    "state": rec.state.value,
                    "failure_rate": round(frate, 4),
                    "avg_latency_ms": round(avg_lat, 1),
                    "total_requests": total,
                    "consecutive_failures": rec.failure_count,
                    "last_failure": rec.last_failure_time if rec.last_failure_time else None,
                }
                providers[prov][mdl] = entry

                if rec.state == CircuitState.CLOSED:
                    healthy += 1
                elif rec.state == CircuitState.HALF_OPEN:
                    degraded += 1
                else:
                    down += 1

            return {
                "system_state": self._system_state.value,
                "providers": dict(providers),
                "summary": {"healthy": healthy, "degraded": degraded, "down": down},
            }

    # ------------------------------------------------------------------
    # Internal helpers (must be called under lock)
    # ------------------------------------------------------------------

    def _check_system_level(self) -> None:
        """Level 3: trip system breaker if all providers are degraded."""
        if not self._provider_windows:
            return
        rate_threshold = self._threshold.current_failure_rate()
        all_bad = all(
            win.total >= 5 and win.failure_rate > rate_threshold
            for win in self._provider_windows.values()
        )
        if all_bad and self._system_state != CircuitState.OPEN:
            self._system_state = CircuitState.OPEN
            self._system_forced_reason = "All providers exceed failure-rate threshold"
            logger.critical("SYSTEM BREAKER OPEN — all providers degraded")

    def _check_system_recovery(self) -> None:
        """Re-close system breaker if any provider recovers."""
        if self._system_state != CircuitState.OPEN:
            return
        rate_threshold = self._threshold.current_failure_rate()
        any_ok = any(
            win.failure_rate <= rate_threshold
            for win in self._provider_windows.values()
            if win.total >= 5
        )
        if any_ok:
            self._system_state = CircuitState.CLOSED
            self._system_forced_reason = None
            logger.info("SYSTEM BREAKER CLOSED — at least one provider recovered")
