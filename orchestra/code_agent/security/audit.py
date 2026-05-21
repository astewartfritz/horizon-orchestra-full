from __future__ import annotations

import csv
import time
import uuid
from dataclasses import dataclass, field
from typing import Any


__all__ = [
    "AuditEvent",
    "AuditStore",
]


@dataclass
class AuditEvent:
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    actor_id: str = ""
    actor_type: str = ""
    action: str = ""
    resource: str = ""
    data_sensitivity: str = ""
    consent_used: str = ""
    ip_address: str = ""
    user_agent: str = ""
    outcome: str = ""
    details: dict = field(default_factory=dict)


class AuditStore:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    def record(self, event: AuditEvent) -> str:
        self._events.append(event)
        return event.event_id

    def query(
        self,
        actor_id: str = "",
        event_type: str = "",
        resource: str = "",
        start_time: float = 0,
        end_time: float = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        results = list(self._events)

        if actor_id:
            results = [e for e in results if e.actor_id == actor_id]
        if event_type:
            results = [e for e in results if e.event_type == event_type]
        if resource:
            results = [e for e in results if e.resource == resource]
        if start_time:
            results = [e for e in results if e.timestamp >= start_time]
        if end_time:
            results = [e for e in results if e.timestamp <= end_time]

        return [self._event_to_dict(e) for e in results[:limit]]

    def export_csv(self, path: str) -> int:
        if not self._events:
            return 0
        fieldnames = [
            "event_id", "timestamp", "event_type", "actor_id", "actor_type",
            "action", "resource", "data_sensitivity", "consent_used",
            "ip_address", "user_agent", "outcome", "details",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for event in self._events:
                writer.writerow(self._event_to_dict(event))
        return len(self._events)

    def count_by_type(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self._events:
            counts[event.event_type] = counts.get(event.event_type, 0) + 1
        return counts

    def count_by_sensitivity(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self._events:
            key = event.data_sensitivity or "unspecified"
            counts[key] = counts.get(key, 0) + 1
        return counts

    def get_recent(self, limit: int = 50) -> list[dict[str, Any]]:
        return [self._event_to_dict(e) for e in self._events[-limit:]]

    @staticmethod
    def _event_to_dict(event: AuditEvent) -> dict[str, Any]:
        return {
            "event_id": event.event_id,
            "timestamp": event.timestamp,
            "event_type": event.event_type,
            "actor_id": event.actor_id,
            "actor_type": event.actor_type,
            "action": event.action,
            "resource": event.resource,
            "data_sensitivity": event.data_sensitivity,
            "consent_used": event.consent_used,
            "ip_address": event.ip_address,
            "user_agent": event.user_agent,
            "outcome": event.outcome,
            "details": event.details,
        }


_store: AuditStore = AuditStore()
