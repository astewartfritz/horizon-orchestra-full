from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class RateLimitRule:
    max_calls: int = 60
    window_seconds: int = 60
    provider: str = "openai"


class RateLimiter:
    """Token-bucket rate limiter per provider."""

    def __init__(self):
        self._rules: dict[str, RateLimitRule] = {
            "openai": RateLimitRule(provider="openai", max_calls=60, window_seconds=60),
            "anthropic": RateLimitRule(provider="anthropic", max_calls=50, window_seconds=60),
            "ollama": RateLimitRule(provider="ollama", max_calls=100, window_seconds=60),
        }
        self._buckets: dict[str, list[float]] = {}

    def set_rule(self, provider: str, max_calls: int, window_seconds: int = 60) -> None:
        self._rules[provider] = RateLimitRule(provider=provider, max_calls=max_calls, window_seconds=window_seconds)

    def _clean_bucket(self, provider: str) -> None:
        now = time.time()
        rule = self._rules.get(provider)
        if not rule:
            return
        bucket = self._buckets.get(provider, [])
        self._buckets[provider] = [t for t in bucket if now - t < rule.window_seconds]

    def can_call(self, provider: str) -> bool:
        self._clean_bucket(provider)
        rule = self._rules.get(provider)
        if not rule:
            return True
        bucket = self._buckets.get(provider, [])
        return len(bucket) < rule.max_calls

    def record_call(self, provider: str) -> None:
        if provider not in self._buckets:
            self._buckets[provider] = []
        self._buckets[provider].append(time.time())

    async def wait_if_needed(self, provider: str) -> None:
        while not self.can_call(provider):
            await asyncio.sleep(1)

    def get_remaining(self, provider: str) -> int:
        self._clean_bucket(provider)
        rule = self._rules.get(provider)
        if not rule:
            return -1
        bucket = self._buckets.get(provider, [])
        return rule.max_calls - len(bucket)

    def stats(self) -> dict[str, dict[str, Any]]:
        stats: dict[str, dict[str, Any]] = {}
        for provider, rule in self._rules.items():
            remaining = self.get_remaining(provider)
            stats[provider] = {
                "max_calls": rule.max_calls,
                "window_seconds": rule.window_seconds,
                "remaining": remaining,
                "available": remaining > 0,
            }
        return stats
