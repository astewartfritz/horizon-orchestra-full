from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AnomalyDetector",
    "AnomalyEvent",
    "AccessPattern",
    "AnomalyRule",
    "AnomalySeverity",
]

log = logging.getLogger("orchestra.security.anomaly")


class AnomalySeverity:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class AnomalyEvent:
    timestamp: float
    severity: str
    rule_name: str
    actor_id: str
    description: str
    details: dict = field(default_factory=dict)


@dataclass
class AccessPattern:
    """A single access event recorded for anomaly analysis."""
    timestamp: float
    actor_id: str
    action: str
    resource: str
    ip_address: str
    success: bool
    resource_sensitivity: str = "public"


@dataclass
class AnomalyRule:
    name: str
    description: str
    severity: str = AnomalySeverity.MEDIUM


class AnomalyDetector:
    """Detects unusual access patterns from agents and humans.

    Maintains sliding windows of recent access events and flags
    patterns that deviate from baselines.
    """

    def __init__(self, window_seconds: int = 300) -> None:
        self._window = window_seconds
        self._events: deque[AccessPattern] = deque(maxlen=10000)
        self._anomalies: list[AnomalyEvent] = []
        self._rules: list[AnomalyRule] = [
            AnomalyRule("rapid_fire", "Many requests in short time", AnomalySeverity.MEDIUM),
            AnomalyRule("escalating_sensitivity", "Accessing increasingly sensitive data", AnomalySeverity.HIGH),
            AnomalyRule("unusual_hours", "Access outside normal business hours", AnomalySeverity.LOW),
            AnomalyRule("failed_access_spike", "Spike in denied access attempts", AnomalySeverity.HIGH),
            AnomalyRule("resource_scramble", "Accessing many unrelated resources", AnomalySeverity.MEDIUM),
            AnomalyRule("data_exfiltration", "Large volume of sensitive data access", AnomalySeverity.CRITICAL),
        ]

    def record(self, pattern: AccessPattern) -> None:
        """Record an access event and run anomaly checks."""
        self._events.append(pattern)
        for rule in self._rules:
            check = getattr(self, f"_check_{rule.name}", None)
            if check:
                result = check(pattern)
                if result:
                    self._anomalies.append(AnomalyEvent(
                        timestamp=time.time(),
                        severity=rule.severity,
                        rule_name=rule.name,
                        actor_id=pattern.actor_id,
                        description=result,
                        details={"action": pattern.action, "resource": pattern.resource},
                    ))

    def add_rule(self, rule: AnomalyRule) -> None:
        """Register a custom anomaly rule."""
        self._rules.append(rule)

    def get_anomalies(self, since: float = 0, severity: str = "",
                      limit: int = 100) -> list[AnomalyEvent]:
        """Return recent anomalies with optional filters."""
        result = [a for a in self._anomalies if a.timestamp >= since]
        if severity:
            result = [a for a in result if a.severity == severity]
        return result[-limit:]

    def get_actor_summary(self, actor_id: str) -> dict[str, Any]:
        """Return an anomaly summary for a specific actor."""
        actor_events = [e for e in self._events if e.actor_id == actor_id]
        actor_anomalies = [a for a in self._anomalies if a.actor_id == actor_id]
        sensitivities = defaultdict(int)
        for e in actor_events:
            sensitivities[e.resource_sensitivity] += 1
        return {
            "actor_id": actor_id,
            "total_requests": len(actor_events),
            "anomaly_count": len(actor_anomalies),
            "failed_requests": sum(1 for e in actor_events if not e.success),
            "sensitivity_profile": dict(sensitivities),
            "latest_anomalies": [a.description for a in actor_anomalies[-5:]],
        }

    # ── Built-in check rules ──────────────────────────────────────────

    def _check_rapid_fire(self, pattern: AccessPattern) -> str | None:
        """Flag if > 50 requests in the window from one actor."""
        recent = [e for e in self._events
                  if e.actor_id == pattern.actor_id
                  and e.timestamp > time.time() - self._window]
        if len(recent) > 50:
            return f"Rapid fire: {len(recent)} requests in {self._window}s window"
        return None

    def _check_escalating_sensitivity(self, pattern: AccessPattern) -> str | None:
        """Flag if actor is rapidly escalating data sensitivity."""
        order = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3, "critical": 4}
        recent = [e for e in self._events
                  if e.actor_id == pattern.actor_id
                  and e.timestamp > time.time() - 60]
        if len(recent) < 3:
            return None
        levels = [order.get(e.resource_sensitivity, 0) for e in recent[-5:]]
        if len(levels) >= 3 and all(levels[i] < levels[i + 1] for i in range(len(levels) - 1)):
            return f"Escalating sensitivity: {' → '.join(repr(l) for l in levels)}"
        return None

    def _check_unusual_hours(self, pattern: AccessPattern) -> str | None:
        """Flag if access is between 11 PM and 6 AM local."""
        local_hour = time.localtime(pattern.timestamp).tm_hour
        if local_hour < 6 or local_hour >= 23:
            return f"Unusual hour access at {local_hour}:00"
        return None

    def _check_failed_access_spike(self, pattern: AccessPattern) -> str | None:
        """Flag if > 10 failed attempts in 5 minutes."""
        recent = [e for e in self._events
                  if e.actor_id == pattern.actor_id
                  and not e.success
                  and e.timestamp > time.time() - 300]
        if len(recent) > 10:
            return f"Failed access spike: {len(recent)} denials in 5 minutes"
        return None

    def _check_resource_scramble(self, pattern: AccessPattern) -> str | None:
        """Flag if accessing many different resources in short time."""
        recent = [e for e in self._events
                  if e.actor_id == pattern.actor_id
                  and e.timestamp > time.time() - 60]
        unique = set(e.resource for e in recent)
        if len(unique) > 10:
            return f"Resource scramble: {len(unique)} unique resources in 60s"
        return None

    def _check_data_exfiltration(self, pattern: AccessPattern) -> str | None:
        """Flag if accessing restricted/critical data at high volume."""
        recent = [e for e in self._events
                  if e.actor_id == pattern.actor_id
                  and e.resource_sensitivity in ("restricted", "critical")
                  and e.timestamp > time.time() - self._window]
        if len(recent) > 30:
            return f"Data exfiltration risk: {len(recent)} sensitive accesses in {self._window}s"
        return None
