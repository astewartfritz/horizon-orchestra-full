from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AdkGovernanceMonitor",
    "GovernanceReport",
]


@dataclass
class GovernanceReport:
    """Snapshot of agent governance metrics."""
    timestamp: float = 0.0
    total_calls: int = 0
    intent_success_count: int = 0
    intent_failure_count: int = 0
    intent_success_rate: float = 0.0
    error_count: int = 0
    error_frequency: dict[str, int] = field(default_factory=dict)
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    anomaly_count: int = 0
    governance_violations: int = 0


class AdkGovernanceMonitor:
    """Tracks agent performance, intent success rates, error
    frequency, latency, and governance compliance in real time.

    Provides the data needed to ensure agents remain compliant
    with governance policies and SLAs.
    """

    def __init__(self) -> None:
        self._intents: dict[str, list[dict[str, Any]]] = {}
        self._errors: dict[str, int] = {}
        self._anomalies: list[dict[str, Any]] = []
        self._violations: list[dict[str, Any]] = []
        self._latencies: list[float] = []
        self._lock = threading.Lock()

    def record_call(
        self,
        intent: str,
        success: bool,
        latency_ms: float = 0.0,
        error_type: str = "",
    ) -> None:
        with self._lock:
            self._intents.setdefault(intent, []).append({
                "timestamp": time.time(),
                "success": success,
                "latency_ms": latency_ms,
                "error_type": error_type,
            })
            self._latencies.append(latency_ms)
            if not success and error_type:
                self._errors[error_type] = self._errors.get(error_type, 0) + 1

    def record_anomaly(self, description: str, details: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._anomalies.append({
                "timestamp": time.time(),
                "description": description,
                "details": details or {},
            })

    def record_violation(self, policy: str, details: dict[str, Any] | None = None) -> None:
        with self._lock:
            self._violations.append({
                "timestamp": time.time(),
                "policy": policy,
                "details": details or {},
            })

    def report(self) -> GovernanceReport:
        with self._lock:
            all_calls = [c for calls in self._intents.values() for c in calls]
            total = len(all_calls)
            successes = sum(1 for c in all_calls if c["success"])
            failures = total - successes
            latencies = sorted(self._latencies)
            avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
            p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0.0
            return GovernanceReport(
                timestamp=time.time(),
                total_calls=total,
                intent_success_count=successes,
                intent_failure_count=failures,
                intent_success_rate=round((successes / total * 100) if total else 0.0, 2),
                error_count=sum(self._errors.values()),
                error_frequency=dict(self._errors),
                avg_latency_ms=round(avg_lat, 1),
                p95_latency_ms=round(p95, 1),
                anomaly_count=len(self._anomalies),
                governance_violations=len(self._violations),
            )

    def intent_stats(self, intent: str) -> dict[str, Any]:
        with self._lock:
            calls = self._intents.get(intent, [])
            total = len(calls)
            if total == 0:
                return {"intent": intent, "total_calls": 0}
            successes = sum(1 for c in calls if c["success"])
            latencies = [c["latency_ms"] for c in calls]
            return {
                "intent": intent,
                "total_calls": total,
                "success_rate": round(successes / total * 100, 2),
                "avg_latency_ms": round(sum(latencies) / len(latencies), 1),
            }

    def recent_anomalies(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._anomalies, key=lambda a: a["timestamp"], reverse=True)[:limit]

    def recent_violations(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            return sorted(self._violations, key=lambda v: v["timestamp"], reverse=True)[:limit]
