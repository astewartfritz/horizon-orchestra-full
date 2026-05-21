from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SlaGuarantee:
    """A formal SLA commitment."""
    name: str
    target_ms: float
    tolerance_pct: float = 99.5
    description: str = ""


@dataclass
class SlaReport:
    """Snapshot of SLA performance over a window."""
    guarantee_name: str
    total_requests: int
    met: int
    violated: int
    compliance_pct: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    window_seconds: float


class SlaTracker:
    """Tracks API latency against formal SLA guarantees.

    Thread-safe.  Produces compliance reports with percentile
    breakdowns.
    """

    def __init__(self) -> None:
        self._guarantees: dict[str, SlaGuarantee] = {}
        self._latencies: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def register(self, guarantee: SlaGuarantee) -> None:
        with self._lock:
            self._guarantees[guarantee.name] = guarantee
            self._latencies.setdefault(guarantee.name, [])

    def record(self, guarantee_name: str, latency_ms: float) -> None:
        with self._lock:
            if guarantee_name not in self._latencies:
                return
            self._latencies[guarantee_name].append(latency_ms)

    def report(self, guarantee_name: str, window_seconds: float = 3600.0) -> SlaReport | None:
        with self._lock:
            guarantee = self._guarantees.get(guarantee_name)
            if guarantee is None:
                return None
            now = time.time()
            cutoff = now - window_seconds
            recent = [ms for ms in self._latencies[guarantee_name]]
            if not recent:
                return None
            recent.sort()
            total = len(recent)
            met = sum(1 for ms in recent if ms <= guarantee.target_ms)
            violated = total - met
            compliance_pct = (met / total) * 100.0 if total else 0.0
            p50 = recent[int(total * 0.5)] if total else 0.0
            p95 = recent[int(total * 0.95)] if total else 0.0
            p99 = recent[int(total * 0.99)] if total else 0.0
            return SlaReport(
                guarantee_name=guarantee_name,
                total_requests=total,
                met=met,
                violated=violated,
                compliance_pct=round(compliance_pct, 2),
                p50_ms=round(p50, 1),
                p95_ms=round(p95, 1),
                p99_ms=round(p99, 1),
                window_seconds=window_seconds,
            )

    def list_guarantees(self) -> list[SlaGuarantee]:
        with self._lock:
            return list(self._guarantees.values())

    def prune(self, max_age: float = 86400.0) -> int:
        with self._lock:
            pruned = 0
            for name in list(self._latencies.keys()):
                before = len(self._latencies[name])
                self._latencies[name] = [ms for ms in self._latencies[name]]
                pruned += before - len(self._latencies[name])
            return pruned

    @staticmethod
    def default_guarantees() -> list[SlaGuarantee]:
        return [
            SlaGuarantee("chat_completion", 5000.0, 99.0, "LLM chat response generation"),
            SlaGuarantee("api_gateway", 200.0, 99.5, "API gateway request proxying"),
            SlaGuarantee("security_check", 50.0, 99.9, "Security middleware per-request validation"),
            SlaGuarantee("database_query", 100.0, 99.5, "SQLite/PostgreSQL read queries"),
            SlaGuarantee("agent_token_verify", 10.0, 99.9, "Agent token HMAC verification"),
        ]
