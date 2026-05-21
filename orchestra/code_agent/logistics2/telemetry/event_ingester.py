"""Event ingester — high-throughput GPS/ELD/IoT telemetry ingestion (Go-style concurrent pipeline)."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from orchestra.code_agent.logistics2.telemetry.streaming import EventStream


@dataclass
class TelemetryEvent:
    source: str = ""  # gps, eld, weigh_station, iot
    vehicle_id: str = ""
    lat: float = 0.0
    lng: float = 0.0
    speed_kmh: float = 0.0
    heading: float = 0.0
    fuel_level_pct: float = 0.0
    engine_hours: float = 0.0
    odometer_km: float = 0.0
    driver_id: str = ""
    event_type: str = "location_update"
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = time.time()


EventHandler = Callable[[TelemetryEvent], Any]


class EventIngester:
    """High-throughput telemetry ingester — processes GPS/ELD streams concurrently.

    Architecture:
      ingest() → buffer → batch → process → publish to EventStream
    """

    def __init__(self, stream: EventStream | None = None):
        self.stream = stream or EventStream()
        self.handlers: dict[str, list[EventHandler]] = {}
        self._buffer: list[TelemetryEvent] = []
        self._buffer_lock = asyncio.Lock()
        self._batch_size = 100
        self._flush_interval = 1.0
        self._running = False

    def on(self, event_type: str, handler: EventHandler) -> None:
        self.handlers.setdefault(event_type, []).append(handler)

    async def ingest(self, event: TelemetryEvent) -> None:
        """Ingest a single telemetry event."""
        async with self._buffer_lock:
            self._buffer.append(event)
        await self.stream.publish("telemetry", event.__dict__)
        # Process handlers immediately for this event
        handlers = self.handlers.get(event.event_type, []) + self.handlers.get("*", [])
        for handler in handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event)
                else:
                    handler(event)
            except Exception:
                pass
        if len(self._buffer) >= self._batch_size:
            await self._flush()

    async def ingest_batch(self, events: list[TelemetryEvent]) -> int:
        """Ingest a batch of events."""
        async with self._buffer_lock:
            self._buffer.extend(events)
        for e in events:
            await self.stream.publish("telemetry", e.__dict__)
        if len(self._buffer) >= self._batch_size:
            await self._flush()
        return len(events)

    async def _flush(self) -> None:
        """Process buffered events."""
        async with self._buffer_lock:
            batch = self._buffer[:]
            self._buffer.clear()
        for event in batch:
            handlers = self.handlers.get(event.event_type, []) + self.handlers.get("*", [])
            for handler in handlers:
                try:
                    if asyncio.iscoroutinefunction(handler):
                        await handler(event)
                    else:
                        handler(event)
                except Exception:
                    pass

    async def start(self, interval: float = 1.0) -> None:
        self._running = True
        self._flush_interval = interval
        while self._running:
            await asyncio.sleep(self._flush_interval)
            if self._buffer:
                await self._flush()

    def stop(self) -> None:
        self._running = False

    # ── Simulated GPS feed ──────────────────

    async def simulate_gps_feed(self, vehicle_id: str, start_lat: float = 40.7,
                                 start_lng: float = -74.0, num_events: int = 10,
                                 interval: float = 2.0) -> None:
        """Simulate a GPS telemetry feed for testing."""
        lat, lng = start_lat, start_lng
        for _ in range(num_events):
            lat += 0.01 * (1 if _ % 2 == 0 else -1)
            lng += 0.01 * (1 if _ % 3 == 0 else -1)
            event = TelemetryEvent(
                source="gps",
                vehicle_id=vehicle_id,
                lat=round(lat, 4),
                lng=round(lng, 4),
                speed_kmh=round(60 + (_ % 5) * 5, 1),
                fuel_level_pct=round(85 - _ * 2, 1),
                odometer_km=round(10000 + _ * 10),
                event_type="location_update",
            )
            await self.ingest(event)
            await asyncio.sleep(interval)
