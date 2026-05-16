"""Event stream — Kafka/Pulsar-style pub/sub for logistics telemetry."""

from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from typing import Any, Callable


class EventStream:
    """In-memory event stream with topic-based pub/sub and partitioning.

    Kafka/Pulsar-style interface for logistics event streaming.
    """

    def __init__(self):
        self._topics: dict[str, list[Callable]] = defaultdict(list)
        self._history: list[dict[str, Any]] = []
        self._max_history = 10000
        self._partitions: dict[str, int] = defaultdict(int)

    def subscribe(self, topic: str, handler: Callable) -> None:
        self._topics[topic].append(handler)

    def subscribe_all(self, handler: Callable) -> None:
        self._topics["*"].append(handler)

    async def publish(self, topic: str, data: Any) -> None:
        entry = {"topic": topic, "data": data, "timestamp": time.time(),
                 "partition": self._partitions[topic]}
        self._partitions[topic] = (self._partitions[topic] + 1) % 4

        self._history.append(entry)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        for handler in self._topics.get(topic, []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(entry)
                else:
                    handler(entry)
            except Exception:
                pass
        for handler in self._topics.get("*", []):
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(entry)
                else:
                    handler(entry)
            except Exception:
                pass

    def replay(self, topic: str | None = None, since: float = 0,
               limit: int = 100) -> list[dict[str, Any]]:
        events = self._history
        if topic:
            events = [e for e in events if e["topic"] == topic]
        if since:
            events = [e for e in events if e["timestamp"] >= since]
        return events[-limit:]

    def stats(self) -> dict[str, Any]:
        topic_counts = defaultdict(int)
        for e in self._history:
            topic_counts[e["topic"]] += 1
        return {
            "total_events": len(self._history),
            "topics": dict(topic_counts),
            "subscribers": {t: len(h) for t, h in self._topics.items()},
        }
