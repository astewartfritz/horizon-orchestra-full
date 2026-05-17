"""Circuit breaker for Redis connectivity.

States:
  CLOSED   — normal operation, requests go to Redis.
  OPEN     — Redis considered down; skip Redis, use fallback limiter.
  HALF_OPEN — cooldown elapsed; allow one probe request to Redis.
              On success → CLOSED.  On failure → OPEN (reset cooldown).
"""

from __future__ import annotations

import enum
import time


class BreakerState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Lightweight circuit breaker (no asyncio needed — state is synchronous)."""

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 30.0,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at: float = 0.0

    @property
    def state(self) -> BreakerState:
        if self._state is BreakerState.OPEN:
            if time.monotonic() - self._opened_at >= self.cooldown_seconds:
                self._state = BreakerState.HALF_OPEN
        return self._state

    def allow_request(self) -> bool:
        """Return True if a Redis request should be attempted."""
        s = self.state
        if s is BreakerState.CLOSED:
            return True
        if s is BreakerState.HALF_OPEN:
            return True  # allow one probe
        return False  # OPEN

    def record_success(self) -> None:
        """Record a successful Redis call."""
        self._consecutive_failures = 0
        self._state = BreakerState.CLOSED

    def record_failure(self) -> None:
        """Record a failed Redis call."""
        self._consecutive_failures += 1
        if self._consecutive_failures >= self.failure_threshold:
            self._state = BreakerState.OPEN
            self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Fully reset the breaker (testing helper)."""
        self._state = BreakerState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = 0.0
