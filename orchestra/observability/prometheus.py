"""Prometheus-compatible metrics exposition for Horizon Orchestra.

Pure-Python implementation generating Prometheus text exposition format
(OpenMetrics-compatible).  Zero external dependencies — no prometheus_client
needed.  Provides counters, gauges, and histograms with label support,
plus a FastAPI middleware that auto-records request metrics.

Usage::

    from orchestra.observability.prometheus import PrometheusRegistry

    registry = PrometheusRegistry()
    metrics  = registry.collect()   # → Prometheus text format string

    # Mount on FastAPI
    registry.register_routes(app)   # GET /metrics
"""

from __future__ import annotations

import asyncio
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from fastapi import FastAPI, Request, Response

__all__ = [
    "MetricType",
    "Metric",
    "Counter",
    "Gauge",
    "Histogram",
    "PrometheusRegistry",
    "MetricsMiddleware",
    "ORCHESTRA_METRICS",
]


# ── Enums & data classes ──────────────────────────────────────────────

class MetricType(str, Enum):
    """Supported Prometheus metric types."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"
    SUMMARY = "summary"


@dataclass
class Metric:
    """Metadata for a registered metric."""
    name: str
    help: str
    type: MetricType
    labels: List[str] = field(default_factory=list)


# ── Default histogram buckets ─────────────────────────────────────────

DEFAULT_BUCKETS: Tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0,
    2.5, 5.0, 10.0, 30.0, 60.0, float("inf"),
)


# ── Label helpers ─────────────────────────────────────────────────────

def _label_key(labels: Dict[str, str]) -> Tuple[Tuple[str, str], ...]:
    """Return a hashable, sorted tuple of label pairs."""
    return tuple(sorted(labels.items()))


def _format_labels(labels: Dict[str, str]) -> str:
    """Render label dict as Prometheus label string ``{k="v",…}``."""
    if not labels:
        return ""
    inner = ",".join(
        f'{k}="{_escape_label_value(v)}"' for k, v in sorted(labels.items())
    )
    return "{" + inner + "}"


def _escape_label_value(value: str) -> str:
    """Escape backslash, double-quote, and newline in label values."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_help(text: str) -> str:
    """Escape backslash and newline in HELP lines."""
    return text.replace("\\", "\\\\").replace("\n", "\\n")


# ── Metric instrument classes ─────────────────────────────────────────

class Counter:
    """Monotonically-increasing counter with optional labels."""

    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._lock = threading.Lock()
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = {}
        if not label_names:
            self._values[_label_key({})] = 0.0

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        """Increment counter by *amount* (must be >= 0)."""
        if amount < 0:
            raise ValueError("Counter increment must be non-negative")
        key = _label_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def labels(self, **kwargs: str) -> "CounterChild":
        """Return a child bound to specific label values."""
        return CounterChild(self, kwargs)

    def collect(self) -> str:
        """Render Prometheus text exposition lines."""
        lines: List[str] = [
            f"# HELP {self.name} {_escape_help(self.help_text)}",
            f"# TYPE {self.name} counter",
        ]
        with self._lock:
            for lk, val in sorted(self._values.items()):
                lbl = dict(lk)
                lines.append(f"{self.name}_total{_format_labels(lbl)} {_fmt(val)}")
        return "\n".join(lines)


class CounterChild:
    """Label-bound proxy for a Counter."""

    def __init__(self, parent: Counter, labels: Dict[str, str]) -> None:
        self._parent = parent
        self._labels = labels

    def inc(self, amount: float = 1.0) -> None:
        self._parent.inc(amount, **self._labels)


class Gauge:
    """Instantaneous value gauge with optional labels."""

    def __init__(self, name: str, help_text: str, label_names: Sequence[str] = ()) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self._lock = threading.Lock()
        self._values: Dict[Tuple[Tuple[str, str], ...], float] = {}
        if not label_names:
            self._values[_label_key({})] = 0.0

    def set(self, value: float, **labels: str) -> None:
        """Set gauge to *value*."""
        key = _label_key(labels)
        with self._lock:
            self._values[key] = value

    def inc(self, amount: float = 1.0, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels: str) -> None:
        key = _label_key(labels)
        with self._lock:
            self._values[key] = self._values.get(key, 0.0) - amount

    def labels(self, **kwargs: str) -> "GaugeChild":
        return GaugeChild(self, kwargs)

    def collect(self) -> str:
        lines: List[str] = [
            f"# HELP {self.name} {_escape_help(self.help_text)}",
            f"# TYPE {self.name} gauge",
        ]
        with self._lock:
            for lk, val in sorted(self._values.items()):
                lbl = dict(lk)
                lines.append(f"{self.name}{_format_labels(lbl)} {_fmt(val)}")
        return "\n".join(lines)


class GaugeChild:
    """Label-bound proxy for a Gauge."""

    def __init__(self, parent: Gauge, labels: Dict[str, str]) -> None:
        self._parent = parent
        self._labels = labels

    def set(self, value: float) -> None:
        self._parent.set(value, **self._labels)

    def inc(self, amount: float = 1.0) -> None:
        self._parent.inc(amount, **self._labels)

    def dec(self, amount: float = 1.0) -> None:
        self._parent.dec(amount, **self._labels)


class Histogram:
    """Cumulative histogram with configurable bucket boundaries."""

    def __init__(
        self,
        name: str,
        help_text: str,
        label_names: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_BUCKETS,
    ) -> None:
        self.name = name
        self.help_text = help_text
        self.label_names = tuple(label_names)
        self.upper_bounds = tuple(sorted(set(buckets) | {float("inf")}))
        self._lock = threading.Lock()
        # key → {bound: count}, _sum, _count
        self._buckets: Dict[Tuple[Tuple[str, str], ...], Dict[float, int]] = {}
        self._sums: Dict[Tuple[Tuple[str, str], ...], float] = {}
        self._counts: Dict[Tuple[Tuple[str, str], ...], int] = {}
        if not label_names:
            self._init_key(_label_key({}))

    def _init_key(self, key: Tuple[Tuple[str, str], ...]) -> None:
        self._buckets[key] = {b: 0 for b in self.upper_bounds}
        self._sums[key] = 0.0
        self._counts[key] = 0

    def observe(self, value: float, **labels: str) -> None:
        """Record an observation."""
        key = _label_key(labels)
        with self._lock:
            if key not in self._buckets:
                self._init_key(key)
            self._sums[key] += value
            self._counts[key] += 1
            for b in self.upper_bounds:
                if value <= b:
                    self._buckets[key][b] += 1

    def labels(self, **kwargs: str) -> "HistogramChild":
        return HistogramChild(self, kwargs)

    def time(self) -> "_HistogramTimer":
        """Context manager that observes wall-clock seconds."""
        return _HistogramTimer(self)

    def collect(self) -> str:
        lines: List[str] = [
            f"# HELP {self.name} {_escape_help(self.help_text)}",
            f"# TYPE {self.name} histogram",
        ]
        with self._lock:
            for lk in sorted(self._buckets.keys()):
                lbl = dict(lk)
                for b in self.upper_bounds:
                    le = "+Inf" if math.isinf(b) else _fmt(b)
                    bucket_labels = {**lbl, "le": le}
                    lines.append(
                        f"{self.name}_bucket{_format_labels(bucket_labels)} "
                        f"{self._buckets[lk][b]}"
                    )
                lines.append(f"{self.name}_sum{_format_labels(lbl)} {_fmt(self._sums[lk])}")
                lines.append(f"{self.name}_count{_format_labels(lbl)} {self._counts[lk]}")
        return "\n".join(lines)


class HistogramChild:
    """Label-bound proxy for a Histogram."""

    def __init__(self, parent: Histogram, labels: Dict[str, str]) -> None:
        self._parent = parent
        self._labels = labels

    def observe(self, value: float) -> None:
        self._parent.observe(value, **self._labels)

    def time(self) -> "_HistogramTimer":
        return _HistogramTimer(self._parent, self._labels)


class _HistogramTimer:
    """Context-manager timer for histograms."""

    def __init__(self, histogram: Histogram, labels: Optional[Dict[str, str]] = None) -> None:
        self._histogram = histogram
        self._labels = labels or {}
        self._start: float = 0.0

    def __enter__(self) -> "_HistogramTimer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *_: Any) -> None:
        elapsed = time.monotonic() - self._start
        self._histogram.observe(elapsed, **self._labels)


# ── Number formatting ─────────────────────────────────────────────────

def _fmt(value: float) -> str:
    """Format a float for Prometheus text output."""
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if math.isnan(value):
        return "NaN"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.6g}"


# ── Prometheus Registry (singleton) ───────────────────────────────────

class PrometheusRegistry:
    """Central registry for all Prometheus metrics.

    Implements a singleton pattern so every call returns the same instance.

    Example::

        reg = PrometheusRegistry()
        c = reg.counter("http_total", "Total HTTP requests", ["method"])
        c.inc(method="GET")
        print(reg.collect())
    """

    _instance: Optional["PrometheusRegistry"] = None
    _initialized: bool = False

    def __new__(cls) -> "PrometheusRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if PrometheusRegistry._initialized:
            return
        PrometheusRegistry._initialized = True
        self._metrics: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._register_orchestra_metrics()

    # ── Public factory methods ────────────────────────────────────────

    def counter(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
    ) -> Counter:
        """Create or retrieve a Counter metric."""
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]
            c = Counter(name, help_text, labels)
            self._metrics[name] = c
            return c

    def gauge(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
    ) -> Gauge:
        """Create or retrieve a Gauge metric."""
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]
            g = Gauge(name, help_text, labels)
            self._metrics[name] = g
            return g

    def histogram(
        self,
        name: str,
        help_text: str,
        labels: Sequence[str] = (),
        buckets: Sequence[float] = DEFAULT_BUCKETS,
    ) -> Histogram:
        """Create or retrieve a Histogram metric."""
        with self._lock:
            if name in self._metrics:
                return self._metrics[name]
            h = Histogram(name, help_text, labels, buckets)
            self._metrics[name] = h
            return h

    # ── Collection ────────────────────────────────────────────────────

    def collect(self) -> str:
        """Generate the full Prometheus text exposition payload.

        Returns a UTF-8 string conforming to the Prometheus text format.
        """
        blocks: List[str] = []
        with self._lock:
            names = sorted(self._metrics.keys())
        for name in names:
            metric = self._metrics[name]
            blocks.append(metric.collect())
        return "\n\n".join(blocks) + "\n"

    # ── FastAPI integration ───────────────────────────────────────────

    def register_routes(self, app: "FastAPI") -> None:
        """Mount ``GET /metrics`` on a FastAPI application.

        Also installs :class:`MetricsMiddleware` for automatic request
        instrumentation.
        """
        from fastapi import Request
        from fastapi.responses import PlainTextResponse

        @app.get("/metrics", include_in_schema=False)
        async def metrics_endpoint(request: Request) -> PlainTextResponse:
            body = self.collect()
            return PlainTextResponse(
                body,
                media_type="text/plain; version=0.0.4; charset=utf-8",
            )

        app.add_middleware(MetricsMiddleware, registry=self)

    # ── Pre-built Orchestra metrics ───────────────────────────────────

    def _register_orchestra_metrics(self) -> None:
        """Register the standard suite of Horizon Orchestra metrics."""
        self.counter(
            "orchestra_requests_total",
            "Total HTTP requests handled by the Orchestra API",
            labels=["method", "endpoint", "status", "org_id"],
        )
        self.histogram(
            "orchestra_request_duration_seconds",
            "Latency of HTTP requests in seconds",
            labels=["method", "endpoint"],
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, float("inf")),
        )
        self.gauge(
            "orchestra_active_agents",
            "Number of currently active agents",
            labels=["architecture", "org_id"],
        )
        self.counter(
            "orchestra_token_usage_total",
            "Total tokens consumed across all LLM calls",
            labels=["model", "org_id"],
        )
        self.counter(
            "orchestra_tool_calls_total",
            "Total tool invocations",
            labels=["tool", "arch", "result"],
        )
        self.counter(
            "orchestra_team_tasks_total",
            "Total tasks dispatched to multi-orchestrator teams",
            labels=["team", "status"],
        )
        self.gauge(
            "orchestra_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=open, 0.5=half-open)",
            labels=["provider", "model"],
        )
        self.histogram(
            "orchestra_llm_latency_seconds",
            "End-to-end LLM call latency in seconds",
            labels=["model", "provider"],
            buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf")),
        )
        self.counter(
            "orchestra_code_guard_blocks_total",
            "Total code submissions blocked by CodeGuard",
            labels=["threat_type"],
        )
        self.counter(
            "orchestra_ingestion_gate_rejections_total",
            "Total inputs rejected by the ingestion gate",
            labels=["violation_type"],
        )

    # ── Reset (testing only) ──────────────────────────────────────────

    @classmethod
    def _reset(cls) -> None:
        """Reset singleton — intended for tests only."""
        cls._instance = None
        cls._initialized = False


# ── Pre-built metrics convenience dict ────────────────────────────────

ORCHESTRA_METRICS: Dict[str, str] = {
    "orchestra_requests_total": "Total HTTP requests",
    "orchestra_request_duration_seconds": "Request latency histogram",
    "orchestra_active_agents": "Active agent gauge",
    "orchestra_token_usage_total": "Token consumption counter",
    "orchestra_tool_calls_total": "Tool call counter",
    "orchestra_team_tasks_total": "Team task counter",
    "orchestra_circuit_breaker_state": "Circuit breaker gauge",
    "orchestra_llm_latency_seconds": "LLM latency histogram",
    "orchestra_code_guard_blocks_total": "CodeGuard blocks counter",
    "orchestra_ingestion_gate_rejections_total": "Ingestion gate rejections counter",
}


# ── FastAPI middleware ────────────────────────────────────────────────

class MetricsMiddleware:
    """Starlette/FastAPI ASGI middleware that auto-records request metrics.

    Captures ``orchestra_requests_total`` and
    ``orchestra_request_duration_seconds`` for every HTTP request.
    """

    def __init__(self, app: Any, registry: Optional[PrometheusRegistry] = None) -> None:
        self.app = app
        self.registry = registry or PrometheusRegistry()

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET")
        path = scope.get("path", "/")
        status_code = "500"
        start = time.monotonic()

        async def _send_wrapper(message: Dict[str, Any]) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = str(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, _send_wrapper)
        finally:
            duration = time.monotonic() - start
            org_id = scope.get("state", {}).get("org_id", "unknown") if isinstance(scope.get("state"), dict) else "unknown"
            req_counter = self.registry._metrics.get("orchestra_requests_total")
            if req_counter is not None:
                req_counter.inc(
                    method=method,
                    endpoint=path,
                    status=status_code,
                    org_id=org_id,
                )
            req_hist = self.registry._metrics.get("orchestra_request_duration_seconds")
            if req_hist is not None:
                req_hist.observe(duration, method=method, endpoint=path)
