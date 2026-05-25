from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class BreakGlassEvent:
    id: str = ""
    user_id: str = ""
    user_name: str = ""
    reason: str = ""
    resource: str = ""
    granted_at: float = 0.0
    expires_at: float = 0.0
    approved_by: str = ""
    justified: bool = False
    notes: str = ""


class BreakGlassAccess:
    """Emergency access override for healthcare (mandated by HIPAA).

    ``Break-glass`` allows authorized clinicians to access PHI
    outside normal consent parameters during emergencies.  Every
    access is recorded with user, reason, resource, and timestamp
    for mandatory retrospective audit.
    """

    def __init__(self, auto_expire_seconds: float = 900.0) -> None:
        self._events: dict[str, BreakGlassEvent] = {}
        self._auto_expire = auto_expire_seconds

    def grant(
        self, user_id: str, reason: str, resource: str,
        user_name: str = "", approved_by: str = "",
    ) -> BreakGlassEvent:
        event = BreakGlassEvent(
            id=str(uuid.uuid4()),
            user_id=user_id,
            user_name=user_name,
            reason=reason,
            resource=resource,
            granted_at=time.time(),
            expires_at=time.time() + self._auto_expire,
            approved_by=approved_by,
        )
        self._events[event.id] = event
        return event

    def justify(self, event_id: str, notes: str = "") -> bool:
        event = self._events.get(event_id)
        if event is None:
            return False
        event.justified = True
        event.notes = notes
        return True

    def is_active(self, event_id: str) -> bool:
        event = self._events.get(event_id)
        if event is None:
            return False
        return time.time() <= event.expires_at

    def get(self, event_id: str) -> BreakGlassEvent | None:
        return self._events.get(event_id)

    def list_events(self, user_id: str = "") -> list[BreakGlassEvent]:
        if user_id:
            return [e for e in self._events.values() if e.user_id == user_id]
        return list(self._events.values())

    def recent_unjustified(self, limit: int = 20) -> list[BreakGlassEvent]:
        sorted_events = sorted(
            [e for e in self._events.values() if not e.justified],
            key=lambda e: e.granted_at, reverse=True,
        )
        return sorted_events[:limit]

    def summary(self) -> dict[str, Any]:
        total = len(self._events)
        justified = sum(1 for e in self._events.values() if e.justified)
        active = sum(1 for e in self._events.values() if self.is_active(e.id))
        return {
            "total_events": total,
            "justified": justified,
            "unjustified": total - justified,
            "active": active,
            "auto_expire_seconds": self._auto_expire,
        }
