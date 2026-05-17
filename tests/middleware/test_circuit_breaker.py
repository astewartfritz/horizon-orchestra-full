"""Tests for the circuit breaker state machine."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from orchestra.middleware._breaker import BreakerState, CircuitBreaker


class TestCircuitBreaker(unittest.TestCase):
    """State transitions: CLOSED → OPEN → HALF_OPEN → CLOSED."""

    def test_initial_state_is_closed(self):
        cb = CircuitBreaker()
        self.assertEqual(cb.state, BreakerState.CLOSED)
        self.assertTrue(cb.allow_request())

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, BreakerState.CLOSED)
        self.assertTrue(cb.allow_request())

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        self.assertEqual(cb.state, BreakerState.OPEN)
        self.assertFalse(cb.allow_request())

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        # Only 2 consecutive failures, should still be closed
        self.assertEqual(cb.state, BreakerState.CLOSED)

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.1)
        cb.record_failure()
        cb.record_failure()
        self.assertEqual(cb.state, BreakerState.OPEN)

        # Wait for cooldown
        time.sleep(0.15)
        self.assertEqual(cb.state, BreakerState.HALF_OPEN)
        self.assertTrue(cb.allow_request())

    def test_half_open_success_closes(self):
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=0.05)
        cb.record_failure()
        cb.record_failure()
        time.sleep(0.06)
        self.assertEqual(cb.state, BreakerState.HALF_OPEN)
        cb.record_success()
        self.assertEqual(cb.state, BreakerState.CLOSED)

    def test_half_open_failure_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
        cb.record_failure()
        self.assertEqual(cb.state, BreakerState.OPEN)
        time.sleep(0.06)
        self.assertEqual(cb.state, BreakerState.HALF_OPEN)
        cb.record_failure()
        self.assertEqual(cb.state, BreakerState.OPEN)
        # Should block again
        self.assertFalse(cb.allow_request())

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        self.assertEqual(cb.state, BreakerState.OPEN)
        cb.reset()
        self.assertEqual(cb.state, BreakerState.CLOSED)
        self.assertTrue(cb.allow_request())

    def test_open_does_not_allow(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=9999)
        cb.record_failure()
        self.assertFalse(cb.allow_request())

    def test_custom_threshold_and_cooldown(self):
        cb = CircuitBreaker(failure_threshold=10, cooldown_seconds=60)
        for _ in range(9):
            cb.record_failure()
        self.assertEqual(cb.state, BreakerState.CLOSED)
        cb.record_failure()
        self.assertEqual(cb.state, BreakerState.OPEN)


if __name__ == "__main__":
    unittest.main()
