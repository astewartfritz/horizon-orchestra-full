"""Token bucket rate limiter — per-IP, per-user, per-endpoint limits."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from threading import Lock
from typing import Any


@dataclass
class RateLimitRule:
    """Defines a rate limit for a specific scope."""
    requests: int = 60       # Max requests
    window_seconds: int = 60  # Per this window
    scope: str = "ip"         # ip, user, endpoint, global

    def key(self, scope_value: str, endpoint: str = "") -> str:
        if self.scope == "endpoint":
            return f"endpoint:{endpoint}"
        return f"{self.scope}:{scope_value}"


class TokenBucket:
    """Token bucket algorithm for rate limiting."""

    def __init__(self, capacity: int, refill_rate: float, refill_interval: float = 1.0):
        self.capacity = capacity
        self.tokens = float(capacity)
        self.refill_rate = refill_rate
        self.refill_interval = refill_interval
        self.last_refill = time.time()

    def consume(self, tokens: int = 1) -> bool:
        now = time.time()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False


class RateLimiter:
    """Multi-scope rate limiter with token buckets.

    Rules are checked in order: endpoint → user → IP → global.
    First matching rule determines the limit.
    """

    def __init__(self):
        self._buckets: dict[str, TokenBucket] = {}
        self._rules: list[RateLimitRule] = [
            RateLimitRule(requests=10, window_seconds=1, scope="global"),      # 10 req/s global
            RateLimitRule(requests=60, window_seconds=60, scope="ip"),         # 60 req/min per IP
            RateLimitRule(requests=300, window_seconds=60, scope="user"),      # 300 req/min per user
            RateLimitRule(requests=30, window_seconds=60, scope="endpoint"),   # 30 req/min per endpoint
        ]
        self._lock = Lock()

    def add_rule(self, rule: RateLimitRule) -> None:
        with self._lock:
            self._rules.append(rule)

    def _get_bucket(self, key: str, rule: RateLimitRule) -> TokenBucket:
        if key not in self._buckets:
            rate = rule.requests / max(rule.window_seconds, 1)
            self._buckets[key] = TokenBucket(rule.requests, rate)
        return self._buckets[key]

    def check(self, ip: str = "", user: str = "", endpoint: str = "") -> tuple[bool, dict[str, Any]]:
        """Check if request is allowed. Returns (allowed, headers)."""
        with self._lock:
            for rule in self._rules:
                if rule.scope == "endpoint" and endpoint:
                    key = rule.key(endpoint, endpoint)
                elif rule.scope == "user" and user:
                    key = rule.key(user)
                elif rule.scope == "ip" and ip:
                    key = rule.key(ip)
                elif rule.scope == "global":
                    key = "global"
                else:
                    continue

                bucket = self._get_bucket(key, rule)
                allowed = bucket.consume()

                if not allowed:
                    retry_after = int(rule.window_seconds / max(rule.requests, 1))
                    return False, {
                        "Retry-After": str(retry_after),
                        "X-RateLimit-Limit": str(rule.requests),
                        "X-RateLimit-Window": str(rule.window_seconds),
                        "X-RateLimit-Scope": rule.scope,
                    }

        return True, {
            "X-RateLimit-Limit": "60",
            "X-RateLimit-Remaining": "60",
        }

    def cleanup(self, max_age: float = 3600) -> None:
        """Remove stale buckets."""
        now = time.time()
        with self._lock:
            stale = [k for k, b in self._buckets.items() if now - b.last_refill > max_age]
            for k in stale:
                del self._buckets[k]
