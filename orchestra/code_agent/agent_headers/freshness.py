from __future__ import annotations

import threading
import time

from orchestra.code_agent.agent_headers.models import StalenessPolicy

__all__ = [
    "FreshnessTracker",
    "StalenessPolicy",
    "get_last_updated",
    "set_last_updated",
]

_LAST_UPDATED_HEADER = "X-Data-LastUpdated"
_STALENESS_HEADER = "X-Data-Staleness-Accept"

# Module-level singleton
_last_updated: dict[str, float] = {}
_lock = threading.Lock()


def get_last_updated(resource: str) -> float | None:
    with _lock:
        return _last_updated.get(resource)


def set_last_updated(resource: str, timestamp: float | None = None) -> None:
    with _lock:
        _last_updated[resource] = timestamp or time.time()


class FreshnessTracker:
    """Provides ``X-Data-LastUpdated`` and ``X-Data-Staleness-Accept``
    headers so agents can make decisions based on data relevance.

    Agents can declare how stale they are willing to accept via the
    ``X-Data-Staleness-Accept`` header (value in seconds).
    """

    def __init__(self) -> None:
        self._policies: dict[str, StalenessPolicy] = {}

    def register_resource(self, resource: str, policy: StalenessPolicy | None = None) -> None:
        self._policies[resource] = policy or StalenessPolicy()

    def is_fresh(self, resource: str, staleness_seconds: float = 0.0) -> bool:
        ts = get_last_updated(resource)
        if ts is None:
            return False
        policy = self._policies.get(resource, StalenessPolicy())
        max_age = staleness_seconds if staleness_seconds > 0 else policy.max_age_seconds
        return (time.time() - ts) <= max_age

    def format_last_updated_header(self, resource: str) -> str:
        ts = get_last_updated(resource)
        if ts is None:
            return ""
        return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(ts))

    def parse_staleness_accept(self, headers: dict[str, str]) -> float:
        raw = headers.get(_STALENESS_HEADER) or headers.get(_STALENESS_HEADER.lower(), "0")
        try:
            return float(raw)
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def last_updated_header() -> str:
        return _LAST_UPDATED_HEADER

    @staticmethod
    def staleness_header() -> str:
        return _STALENESS_HEADER
