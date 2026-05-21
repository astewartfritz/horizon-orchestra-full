"""Event system — Kafka-style bus for real-time finance signals."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Coroutine

from orchestra.code_agent.finance.models import Transaction


@dataclass
class FinanceEvent:
    """A financial event flowing through the event bus."""
    event_type: str  # tx.created, tx.reconciled, account.updated, insight.generated, signal.ingested
    data: dict[str, Any] = field(default_factory=dict)
    source: str = "system"  # ledger, brain, ingestion, user
    id: str = ""
    timestamp: float = 0.0
    correlation_id: str = ""
    trace_id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "data": self.data,
            "source": self.source,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }


EventHandler = Callable[[FinanceEvent], Coroutine[Any, Any, None]]


class EventBus:
    """In-memory event bus with topic-based pub/sub and replay."""

    def __init__(self):
        self._handlers: dict[str, list[EventHandler]] = {}
        self._history: list[FinanceEvent] = []
        self._max_history = 10000

    def subscribe(self, event_type: str, handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Subscribe to all event types."""
        self._handlers.setdefault("*", []).append(handler)

    async def publish(self, event: FinanceEvent) -> None:
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Dispatch to type-specific handlers
        for handler in self._handlers.get(event.event_type, []):
            try:
                await handler(event)
            except Exception:
                pass

        # Dispatch to wildcard handlers
        for handler in self._handlers.get("*", []):
            try:
                await handler(event)
            except Exception:
                pass

    async def publish_tx(self, tx: Transaction, source: str = "ledger") -> FinanceEvent:
        event = FinanceEvent(
            event_type="tx.created",
            data={
                "id": tx.id,
                "date": tx.date,
                "description": tx.description,
                "type": tx.type.value,
                "amount": sum(e.amount for e in tx.entries),
                "entry_count": len(tx.entries),
                "tags": tx.tags,
            },
            source=source,
        )
        await self.publish(event)
        return event

    def replay(self, event_type: str | None = None,
               since: float = 0, limit: int = 100) -> list[FinanceEvent]:
        events = self._history
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        if since:
            events = [e for e in events if e.timestamp >= since]
        return events[-limit:]

    def clear_history(self) -> None:
        self._history.clear()

    def stats(self) -> dict[str, Any]:
        type_counts: dict[str, int] = {}
        for e in self._history:
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1
        return {
            "total_events": len(self._history),
            "subscribers": sum(len(h) for h in self._handlers.values()),
            "event_types": type_counts,
            "handlers_by_type": {k: len(v) for k, v in self._handlers.items()},
        }


class EventConsumer:
    """Consumer group for processing finance events."""

    def __init__(self, bus: EventBus, group_id: str = "default"):
        self.bus = bus
        self.group_id = group_id
        self._processed: list[str] = []

    async def process(self, event: FinanceEvent) -> None:
        self._processed.append(event.id)

    def get_processed_count(self) -> int:
        return len(self._processed)

    def get_processed_ids(self) -> list[str]:
        return self._processed
