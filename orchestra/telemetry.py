"""Horizon Orchestra — Telemetry + Tracing.

Structured logging, cost tracking, latency metrics, and trace IDs
for debugging agent workflows.  Every tool call, model invocation,
and sub-agent spawn gets a trace entry.

Usage::

    from orchestra.telemetry import Tracer, CostTracker
    tracer = Tracer()
    with tracer.span("agent_loop") as span:
        span.set("model", "kimi-k2.5")
        span.set("tools_called", 15)
    tracer.export()  # → JSON or console
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "Tracer",
    "Span",
    "CostTracker",
    "MetricsCollector",
]

log = logging.getLogger("orchestra.telemetry")


# ---------------------------------------------------------------------------
# Span / Trace
# ---------------------------------------------------------------------------

@dataclass
class Span:
    """A single trace span (unit of work)."""
    name: str
    trace_id: str = ""
    span_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    parent_id: str = ""
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "ok"             # ok, error
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    def set(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, data: dict[str, Any] | None = None) -> None:
        self.events.append({"name": name, "time": time.time(), "data": data or {}})

    def end(self, status: str = "ok") -> None:
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "start": self.start_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "attributes": self.attributes,
            "events": self.events,
        }

    def __enter__(self) -> "Span":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.end(status="error" if exc_type else "ok")
        if exc_type:
            self.set("error", str(exc_val))


class Tracer:
    """Distributed-style tracer for agent workflows."""

    def __init__(self, trace_id: str = "") -> None:
        self.trace_id = trace_id or str(uuid.uuid4())[:12]
        self._spans: list[Span] = []
        self._current_span: Span | None = None

    def span(self, name: str, parent: Span | None = None) -> Span:
        """Create and start a new span."""
        s = Span(
            name=name,
            trace_id=self.trace_id,
            parent_id=parent.span_id if parent else (
                self._current_span.span_id if self._current_span else ""
            ),
        )
        self._spans.append(s)
        self._current_span = s
        return s

    def get_spans(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._spans]

    def export_json(self, path: str = "") -> str:
        """Export all spans as JSON."""
        data = {
            "trace_id": self.trace_id,
            "span_count": len(self._spans),
            "total_duration_ms": sum(s.duration_ms for s in self._spans if s.end_time),
            "spans": self.get_spans(),
        }
        output = json.dumps(data, indent=2)
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            Path(path).write_text(output)
        return output

    def summary(self) -> dict[str, Any]:
        """Quick summary of the trace."""
        errors = [s for s in self._spans if s.status == "error"]
        return {
            "trace_id": self.trace_id,
            "total_spans": len(self._spans),
            "total_duration_ms": round(sum(s.duration_ms for s in self._spans if s.end_time), 2),
            "errors": len(errors),
            "slowest_span": max(
                ({"name": s.name, "duration_ms": s.duration_ms} for s in self._spans if s.end_time),
                key=lambda x: x["duration_ms"],
                default=None,
            ),
        }


# ---------------------------------------------------------------------------
# Cost tracking
# ---------------------------------------------------------------------------

@dataclass
class ModelCall:
    model: str
    provider: str
    input_tokens: int
    output_tokens: int
    cost: float
    timestamp: float = field(default_factory=time.time)
    latency_ms: float = 0.0


class CostTracker:
    """Track token usage and costs across model calls.

    Pricing is pulled from the ModelRouter's config.
    """

    def __init__(self) -> None:
        self._calls: list[ModelCall] = []

    def record(
        self,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        cost_input_per_m: float,
        cost_output_per_m: float,
        latency_ms: float = 0.0,
    ) -> ModelCall:
        """Record a model API call."""
        cost = (input_tokens * cost_input_per_m + output_tokens * cost_output_per_m) / 1_000_000
        call = ModelCall(
            model=model,
            provider=provider,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=round(cost, 6),
            latency_ms=latency_ms,
        )
        self._calls.append(call)
        return call

    @property
    def total_cost(self) -> float:
        return round(sum(c.cost for c in self._calls), 6)

    @property
    def total_tokens(self) -> dict[str, int]:
        return {
            "input": sum(c.input_tokens for c in self._calls),
            "output": sum(c.output_tokens for c in self._calls),
            "total": sum(c.input_tokens + c.output_tokens for c in self._calls),
        }

    def by_model(self) -> dict[str, dict[str, Any]]:
        """Breakdown by model."""
        models: dict[str, dict[str, Any]] = {}
        for c in self._calls:
            if c.model not in models:
                models[c.model] = {"calls": 0, "cost": 0, "input_tokens": 0, "output_tokens": 0, "avg_latency_ms": 0}
            m = models[c.model]
            m["calls"] += 1
            m["cost"] = round(m["cost"] + c.cost, 6)
            m["input_tokens"] += c.input_tokens
            m["output_tokens"] += c.output_tokens
            m["avg_latency_ms"] = round(
                (m["avg_latency_ms"] * (m["calls"] - 1) + c.latency_ms) / m["calls"], 2
            )
        return models

    def summary(self) -> dict[str, Any]:
        return {
            "total_calls": len(self._calls),
            "total_cost": self.total_cost,
            "total_tokens": self.total_tokens,
            "by_model": self.by_model(),
        }


# ---------------------------------------------------------------------------
# Metrics collector
# ---------------------------------------------------------------------------

class MetricsCollector:
    """Collect and aggregate operational metrics."""

    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._gauges: dict[str, float] = {}
        self._histograms: dict[str, list[float]] = {}

    def increment(self, name: str, value: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def gauge(self, name: str, value: float) -> None:
        self._gauges[name] = value

    def observe(self, name: str, value: float) -> None:
        """Add a value to a histogram (for latency, duration, etc)."""
        if name not in self._histograms:
            self._histograms[name] = []
        self._histograms[name].append(value)

    def summary(self) -> dict[str, Any]:
        hist_summary = {}
        for name, values in self._histograms.items():
            if values:
                sorted_v = sorted(values)
                n = len(sorted_v)
                hist_summary[name] = {
                    "count": n,
                    "mean": round(sum(values) / n, 3),
                    "min": round(sorted_v[0], 3),
                    "max": round(sorted_v[-1], 3),
                    "p50": round(sorted_v[n // 2], 3),
                    "p95": round(sorted_v[int(n * 0.95)], 3) if n > 1 else round(sorted_v[0], 3),
                    "p99": round(sorted_v[int(n * 0.99)], 3) if n > 1 else round(sorted_v[0], 3),
                }
        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": hist_summary,
        }
