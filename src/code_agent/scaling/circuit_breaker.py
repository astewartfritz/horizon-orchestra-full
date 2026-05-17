from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    """Per-lane circuit breaker to prevent cascade failures.

    States:
      CLOSED  → normal operation, requests pass through
      OPEN    → failures exceeded threshold, requests fail fast
      HALF_OPEN → probation period, one test request allowed

    Transitions:
      CLOSED → OPEN: failure_threshold exceeded in window
      OPEN → HALF_OPEN: reset_timeout elapsed
      HALF_OPEN → CLOSED: test request succeeds
      HALF_OPEN → OPEN: test request fails
    """

    name: str
    failure_threshold: int = 5
    reset_timeout: float = 30.0
    half_open_max_requests: int = 1

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = field(default_factory=time.time)
    half_open_requests: int = 0
    total_failures: int = 0
    total_successes: int = 0
    consecutive_successes: int = 0

    def record_success(self):
        self.total_successes += 1
        self.consecutive_successes += 1
        if self.state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.CLOSED)
            self.failure_count = 0
        elif self.state == CircuitState.CLOSED:
            self.failure_count = 0

    def record_failure(self):
        self.total_failures += 1
        self.consecutive_successes = 0
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN)
        elif self.state == CircuitState.CLOSED:
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self._transition(CircuitState.OPEN)

    def allow_request(self) -> bool:
        now = time.time()

        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if now - self.last_state_change >= self.reset_timeout:
                self._transition(CircuitState.HALF_OPEN)
                self.half_open_requests = 0
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            if self.half_open_requests < self.half_open_max_requests:
                self.half_open_requests += 1
                return True
            return False

        return True

    def _transition(self, new_state: CircuitState):
        self.state = new_state
        self.last_state_change = time.time()
        if new_state == CircuitState.CLOSED:
            self.failure_count = 0
            self.half_open_requests = 0

    def reset(self):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = 0.0
        self.last_state_change = time.time()
        self.half_open_requests = 0
        self.consecutive_successes = 0

    @property
    def is_open(self) -> bool:
        return self.state == CircuitState.OPEN

    @property
    def is_closed(self) -> bool:
        return self.state == CircuitState.CLOSED

    def summary(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self.failure_count,
            "failure_threshold": self.failure_threshold,
            "total_failures": self.total_failures,
            "total_successes": self.total_successes,
            "consecutive_successes": self.consecutive_successes,
            "is_open": self.is_open,
        }


class CircuitBreakerRegistry:
    """Manages circuit breakers per lane/model."""

    def __init__(self):
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str, **kwargs) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name=name, **kwargs)
        return self._breakers[name]

    def record_success(self, name: str, **kwargs):
        cb = self.get(name, **kwargs)
        cb.record_success()

    def record_failure(self, name: str, **kwargs):
        cb = self.get(name, **kwargs)
        cb.record_failure()

    def allow_request(self, name: str, **kwargs) -> bool:
        cb = self.get(name, **kwargs)
        return cb.allow_request()

    def all_summaries(self) -> dict[str, dict]:
        return {name: cb.summary() for name, cb in self._breakers.items()}

    def reset_all(self):
        for cb in self._breakers.values():
            cb.reset()
