from __future__ import annotations

import re
import threading
import time
from typing import Any

from orchestra.code_agent.agent_headers.models import RateLimitPolicy

__all__ = [
    "RateLimitPolicy",
    "RateLimitStore",
    "parse_error_recovery",
]

_RATE_LIMIT_REMAINING_HEADER = "X-RateLimit-Remaining"
_RATE_LIMIT_RESET_HEADER = "X-RateLimit-Reset"
_RATE_LIMIT_LIMIT_HEADER = "X-RateLimit-Limit"
_ERROR_RECOVERY_HEADER = "X-Error-Recovery"

_RETRY_AFTER_RE = re.compile(r"retryafter\s*=\s*(\d+)", re.IGNORECASE)


def parse_error_recovery(headers: dict[str, str]) -> dict[str, Any]:
    """Parse the ``X-Error-Recovery`` header for retry guidance.

    Returns a dict with keys like ``retry_after`` (seconds).
    """
    raw = headers.get(_ERROR_RECOVERY_HEADER) or headers.get(_ERROR_RECOVERY_HEADER.lower(), "")
    result: dict[str, Any] = {}
    match = _RETRY_AFTER_RE.search(raw)
    if match:
        result["retry_after"] = int(match.group(1))
    if not result:
        result["strategy"] = raw.strip() or "unknown"
    return result


class RateLimitStore:
    """Tracks per-agent request counts and enforces rate limits.

    Produces standard ``X-RateLimit-Remaining``, ``X-RateLimit-Reset``,
    and ``X-RateLimit-Limit`` headers so agents can manage their quotas.
    """

    def __init__(self) -> None:
        self._counts: dict[str, list[float]] = {}
        self._lock = threading.Lock()
        self._default_policy = RateLimitPolicy()

    def set_policy(self, agent_id: str, policy: RateLimitPolicy) -> None:
        with self._lock:
            self._counts.setdefault(agent_id, [])
        self._default_policy = policy

    def check(self, agent_id: str, policy: RateLimitPolicy | None = None) -> dict[str, int]:
        now = time.time()
        p = policy or self._default_policy
        window_min = 60.0
        window_hour = 3600.0

        with self._lock:
            timestamps = self._counts.setdefault(agent_id, [])
            recent_min = [t for t in timestamps if now - t < window_min]
            recent_hour = [t for t in timestamps if now - t < window_hour]

            if len(recent_min) >= p.requests_per_minute:
                return {
                    "allowed": 0,
                    "remaining": 0,
                    "reset": int(window_min - (now - recent_min[0])),
                    "limit": p.requests_per_minute,
                    "reason": "minute_limit_exceeded",
                }
            if len(recent_hour) >= p.requests_per_hour:
                return {
                    "allowed": 0,
                    "remaining": 0,
                    "reset": int(window_hour - (now - recent_hour[0])),
                    "limit": p.requests_per_hour,
                    "reason": "hour_limit_exceeded",
                }

            timestamps.append(now)
            remaining_min = p.requests_per_minute - len(recent_min) - 1
            return {
                "allowed": 1,
                "remaining": max(0, remaining_min),
                "reset": int(window_min),
                "limit": p.requests_per_minute,
            }

    def format_headers(self, result: dict[str, int]) -> list[tuple[str, str]]:
        return [
            (_RATE_LIMIT_REMAINING_HEADER, str(result.get("remaining", 0))),
            (_RATE_LIMIT_RESET_HEADER, str(result.get("reset", 60))),
            (_RATE_LIMIT_LIMIT_HEADER, str(result.get("limit", 60))),
        ]

    @staticmethod
    def error_recovery_header() -> str:
        return _ERROR_RECOVERY_HEADER

    @staticmethod
    def format_error_recovery(retry_after: int) -> str:
        return f"RetryAfter={retry_after}s"
