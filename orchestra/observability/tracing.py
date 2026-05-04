"""Distributed tracing for Horizon Orchestra (OpenTelemetry-compatible).

Provides W3C Trace Context propagation, span lifecycle management, and
export to Jaeger, Zipkin, and OTLP backends.  Zero external dependencies
— only the Python stdlib is required.

Usage::

    from orchestra.observability.tracing import OrchestraTracer, traced

    tracer = OrchestraTracer(service_name="orchestra-api")

    @traced(name="handle_request")
    async def handle(req):
        span = tracer.start_span("db_query")
        ...
        tracer.end_span(span)
"""

from __future__ import annotations

import asyncio
import functools
import json
import logging
import os
import random
import struct
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import (
    Any,
    Callable,
    Deque,
    Dict,
    List,
    Optional,
    Sequence,
    TYPE_CHECKING,
)

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = [
    "TraceContext",
    "Span",
    "SpanStatus",
    "OrchestraTracer",
    "traced",
    "traced_tool",
]

logger = logging.getLogger("orchestra.observability.tracing")


# ── ID generation helpers ─────────────────────────────────────────────

def _new_trace_id() -> str:
    """Generate a 32-hex-char W3C trace-id."""
    return uuid.uuid4().hex

def _new_span_id() -> str:
    """Generate a 16-hex-char W3C span-id."""
    return os.urandom(8).hex()


# ── Data classes ──────────────────────────────────────────────────────

class SpanStatus:
    """Standard span status values."""
    OK = "OK"
    ERROR = "ERROR"
    UNSET = "UNSET"


@dataclass
class TraceContext:
    """W3C Trace Context propagation object."""

    trace_id: str = field(default_factory=_new_trace_id)
    span_id: str = field(default_factory=_new_span_id)
    parent_span_id: Optional[str] = None
    sampling_rate: float = 1.0
    baggage: Dict[str, str] = field(default_factory=dict)

    @property
    def trace_flags(self) -> str:
        """Return trace flags byte as 2-hex string (sampled = 01)."""
        return "01" if self.sampling_rate > 0 else "00"


@dataclass
class SpanEvent:
    """A timestamped annotation within a span."""
    name: str
    timestamp_ns: int = field(default_factory=lambda: time.time_ns())
    attributes: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """A single span within a distributed trace."""

    trace_id: str = field(default_factory=_new_trace_id)
    span_id: str = field(default_factory=_new_span_id)
    parent_span_id: Optional[str] = None
    name: str = ""
    service: str = "horizon-orchestra"
    start_ns: int = field(default_factory=lambda: time.time_ns())
    end_ns: Optional[int] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[SpanEvent] = field(default_factory=list)
    status: str = SpanStatus.UNSET
    error: Optional[str] = None

    @property
    def duration_ns(self) -> int:
        """Duration in nanoseconds (0 if span still open)."""
        if self.end_ns is None:
            return 0
        return self.end_ns - self.start_ns

    @property
    def duration_ms(self) -> float:
        """Duration in milliseconds."""
        return self.duration_ns / 1_000_000


# ── Orchestra Tracer ──────────────────────────────────────────────────

class OrchestraTracer:
    """Distributed tracer with W3C context propagation and multi-backend export.

    Parameters
    ----------
    service_name : str
        Logical service name for all spans created by this tracer.
    sampling_rate : float
        Probability [0.0, 1.0] that a new root trace will be sampled.
    max_spans : int
        Maximum finished spans kept in the in-memory buffer.
    """

    def __init__(
        self,
        service_name: str = "horizon-orchestra",
        sampling_rate: float = 1.0,
        max_spans: int = 10_000,
    ) -> None:
        self.service_name = service_name
        self.sampling_rate = sampling_rate
        self.max_spans = max_spans

        self._lock = threading.Lock()
        self._active_spans: Dict[str, Span] = {}
        self._finished_spans: Deque[Span] = deque(maxlen=max_spans)

    # ── Span lifecycle ────────────────────────────────────────────────

    def start_span(
        self,
        name: str,
        parent: Optional[Span] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> Span:
        """Create and start a new span.

        If *parent* is given the new span inherits the trace-id.
        """
        if parent is not None:
            trace_id = parent.trace_id
            parent_span_id = parent.span_id
        else:
            trace_id = _new_trace_id()
            parent_span_id = None

        span = Span(
            trace_id=trace_id,
            span_id=_new_span_id(),
            parent_span_id=parent_span_id,
            name=name,
            service=self.service_name,
            attributes=attributes or {},
        )

        with self._lock:
            self._active_spans[span.span_id] = span
        return span

    def end_span(
        self,
        span: Span,
        status: str = SpanStatus.OK,
        error: Optional[str] = None,
    ) -> None:
        """Finish a span and move it to the completed buffer."""
        span.end_ns = time.time_ns()
        span.status = status
        if error:
            span.error = error
            span.status = SpanStatus.ERROR

        with self._lock:
            self._active_spans.pop(span.span_id, None)
            self._finished_spans.append(span)

    def add_event(
        self,
        span: Span,
        name: str,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Attach a timestamped event to a span."""
        span.events.append(SpanEvent(
            name=name,
            attributes=attributes or {},
        ))

    # ── W3C Trace Context propagation ─────────────────────────────────

    def inject_context(self, span: Span, headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Inject W3C ``traceparent`` (and ``tracestate``) into HTTP headers.

        Returns the updated headers dict.
        """
        if headers is None:
            headers = {}
        trace_flags = "01"  # sampled
        headers["traceparent"] = (
            f"00-{span.trace_id}-{span.span_id}-{trace_flags}"
        )
        headers["tracestate"] = f"orchestra={span.span_id}"
        return headers

    def extract_context(self, headers: Dict[str, str]) -> Optional[TraceContext]:
        """Extract a :class:`TraceContext` from incoming HTTP headers.

        Parses the W3C ``traceparent`` header.  Returns ``None`` if the
        header is missing or malformed.
        """
        tp = headers.get("traceparent", "")
        if not tp:
            # Try case-insensitive lookup
            for k, v in headers.items():
                if k.lower() == "traceparent":
                    tp = v
                    break
        if not tp:
            return None

        parts = tp.split("-")
        if len(parts) < 4:
            return None

        version, trace_id, parent_span_id, flags = parts[0], parts[1], parts[2], parts[3]
        if len(trace_id) != 32 or len(parent_span_id) != 16:
            return None

        sampling_rate = 1.0 if flags == "01" else 0.0

        # Parse baggage
        baggage: Dict[str, str] = {}
        baggage_header = headers.get("baggage", "")
        if baggage_header:
            for pair in baggage_header.split(","):
                if "=" in pair:
                    k, v = pair.strip().split("=", 1)
                    baggage[k.strip()] = v.strip()

        return TraceContext(
            trace_id=trace_id,
            span_id=parent_span_id,
            parent_span_id=None,
            sampling_rate=sampling_rate,
            baggage=baggage,
        )

    # ── Export: Jaeger ────────────────────────────────────────────────

    def export_jaeger(self, span: Span) -> Dict[str, Any]:
        """Export a span as a Jaeger-compatible JSON object.

        Compatible with the Jaeger ``/api/traces`` ingest endpoint.
        """
        return {
            "traceID": span.trace_id,
            "spanID": span.span_id,
            "operationName": span.name,
            "references": (
                [{"refType": "CHILD_OF", "traceID": span.trace_id, "spanID": span.parent_span_id}]
                if span.parent_span_id else []
            ),
            "startTime": span.start_ns // 1_000,  # microseconds
            "duration": span.duration_ns // 1_000,
            "tags": [
                {"key": "service.name", "type": "string", "value": span.service},
                {"key": "otel.status_code", "type": "string", "value": span.status},
                *[
                    {"key": k, "type": "string", "value": str(v)}
                    for k, v in span.attributes.items()
                ],
            ],
            "logs": [
                {
                    "timestamp": ev.timestamp_ns // 1_000,
                    "fields": [
                        {"key": "event", "type": "string", "value": ev.name},
                        *[
                            {"key": k, "type": "string", "value": str(v)}
                            for k, v in ev.attributes.items()
                        ],
                    ],
                }
                for ev in span.events
            ],
            "processID": "p1",
            "process": {
                "serviceName": span.service,
                "tags": [],
            },
        }

    # ── Export: Zipkin ────────────────────────────────────────────────

    def export_zipkin(self, span: Span) -> Dict[str, Any]:
        """Export a span as a Zipkin v2 JSON object."""
        obj: Dict[str, Any] = {
            "traceId": span.trace_id,
            "id": span.span_id,
            "name": span.name,
            "timestamp": span.start_ns // 1_000,  # microseconds
            "duration": span.duration_ns // 1_000,
            "localEndpoint": {
                "serviceName": span.service,
            },
            "tags": {k: str(v) for k, v in span.attributes.items()},
            "annotations": [
                {"timestamp": ev.timestamp_ns // 1_000, "value": ev.name}
                for ev in span.events
            ],
        }
        if span.parent_span_id:
            obj["parentId"] = span.parent_span_id
        if span.status == SpanStatus.ERROR:
            obj["tags"]["error"] = span.error or "true"
        return obj

    # ── Export: OTLP (simplified JSON, not protobuf) ──────────────────

    def export_otlp(self, spans: Sequence[Span]) -> bytes:
        """Export spans as OTLP-compatible JSON (simplified).

        Returns UTF-8 encoded bytes matching the OTLP JSON structure.
        For production use, a full protobuf serialiser is recommended.
        """
        resource_spans = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": self.service_name}},
                        ],
                    },
                    "scopeSpans": [
                        {
                            "scope": {"name": "orchestra.tracer", "version": "1.0.0"},
                            "spans": [self._otlp_span(s) for s in spans],
                        },
                    ],
                },
            ],
        }
        return json.dumps(resource_spans).encode("utf-8")

    def _otlp_span(self, span: Span) -> Dict[str, Any]:
        """Convert a single span to OTLP JSON representation."""
        status_code = 1 if span.status == SpanStatus.OK else (2 if span.status == SpanStatus.ERROR else 0)
        return {
            "traceId": span.trace_id,
            "spanId": span.span_id,
            "parentSpanId": span.parent_span_id or "",
            "name": span.name,
            "kind": 1,  # SPAN_KIND_INTERNAL
            "startTimeUnixNano": str(span.start_ns),
            "endTimeUnixNano": str(span.end_ns or 0),
            "attributes": [
                {"key": k, "value": {"stringValue": str(v)}}
                for k, v in span.attributes.items()
            ],
            "events": [
                {
                    "timeUnixNano": str(ev.timestamp_ns),
                    "name": ev.name,
                    "attributes": [
                        {"key": k, "value": {"stringValue": str(v)}}
                        for k, v in ev.attributes.items()
                    ],
                }
                for ev in span.events
            ],
            "status": {
                "code": status_code,
                "message": span.error or "",
            },
        }

    # ── Query helpers ─────────────────────────────────────────────────

    def get_active_spans(self) -> List[Span]:
        """Return a snapshot of currently-open spans."""
        with self._lock:
            return list(self._active_spans.values())

    def get_finished_spans(self, limit: int = 100) -> List[Span]:
        """Return the most recent finished spans."""
        with self._lock:
            spans = list(self._finished_spans)
        return spans[-limit:]

    def get_trace(self, trace_id: str) -> List[Span]:
        """Return all known spans for a given trace ID."""
        with self._lock:
            active = [s for s in self._active_spans.values() if s.trace_id == trace_id]
            finished = [s for s in self._finished_spans if s.trace_id == trace_id]
        return active + finished

    # ── FastAPI integration ───────────────────────────────────────────

    def register_routes(self, app: "FastAPI") -> None:
        """Mount debug trace endpoints on a FastAPI application.

        * ``GET /v1/debug/traces`` — list recent traces
        * ``GET /v1/debug/traces/{trace_id}`` — single trace detail
        """
        from fastapi import Request
        from fastapi.responses import JSONResponse

        @app.get("/v1/debug/traces", include_in_schema=False)
        async def list_traces(limit: int = 50) -> JSONResponse:
            spans = self.get_finished_spans(limit)
            # Group by trace_id
            traces: Dict[str, List[Dict[str, Any]]] = {}
            for s in spans:
                traces.setdefault(s.trace_id, []).append(self.export_zipkin(s))
            return JSONResponse({"traces": traces, "count": len(traces)})

        @app.get("/v1/debug/traces/{trace_id}", include_in_schema=False)
        async def get_trace(trace_id: str) -> JSONResponse:
            spans = self.get_trace(trace_id)
            return JSONResponse({
                "trace_id": trace_id,
                "spans": [self.export_zipkin(s) for s in spans],
                "count": len(spans),
            })

        # Install tracing middleware
        @app.middleware("http")
        async def tracing_middleware(request: "Request", call_next: Any) -> Any:
            ctx = self.extract_context(dict(request.headers))
            parent = None
            if ctx:
                parent = Span(
                    trace_id=ctx.trace_id,
                    span_id=ctx.span_id,
                )

            span = self.start_span(
                name=f"{request.method} {request.url.path}",
                parent=parent,
                attributes={
                    "http.method": request.method,
                    "http.url": str(request.url),
                    "http.route": request.url.path,
                },
            )

            try:
                response = await call_next(request)
                span.attributes["http.status_code"] = response.status_code
                status = SpanStatus.OK if response.status_code < 400 else SpanStatus.ERROR
                self.end_span(span, status=status)
                # Inject trace context into response
                response.headers["traceparent"] = (
                    f"00-{span.trace_id}-{span.span_id}-01"
                )
                return response
            except Exception as exc:
                self.end_span(span, status=SpanStatus.ERROR, error=str(exc))
                raise


# ── Decorators ────────────────────────────────────────────────────────

# Module-level default tracer (lazy-init)
_default_tracer: Optional[OrchestraTracer] = None
_tracer_lock = threading.Lock()


def _get_default_tracer() -> OrchestraTracer:
    """Return (and lazily create) the module-level default tracer."""
    global _default_tracer
    if _default_tracer is None:
        with _tracer_lock:
            if _default_tracer is None:
                _default_tracer = OrchestraTracer()
    return _default_tracer


def traced(
    name: Optional[str] = None,
    tracer: Optional[OrchestraTracer] = None,
) -> Callable[..., Any]:
    """Decorator that auto-traces an async function.

    Usage::

        @traced(name="process_request")
        async def process(request):
            ...

    If *name* is ``None`` the function's qualified name is used.
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        span_name = name or fn.__qualname__

        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            t = tracer or _get_default_tracer()
            span = t.start_span(span_name, attributes={
                "code.function": fn.__name__,
                "code.namespace": fn.__module__,
            })
            try:
                result = await fn(*args, **kwargs)
                t.end_span(span, status=SpanStatus.OK)
                return result
            except Exception as exc:
                t.end_span(span, status=SpanStatus.ERROR, error=str(exc))
                raise

        return wrapper
    return decorator


def traced_tool(
    tool_name: str,
    tracer: Optional[OrchestraTracer] = None,
) -> Callable[..., Any]:
    """Decorator that auto-traces tool calls with standard attributes.

    Usage::

        @traced_tool("web_search")
        async def web_search(query: str):
            ...
    """
    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            t = tracer or _get_default_tracer()
            span = t.start_span(f"tool.{tool_name}", attributes={
                "tool.name": tool_name,
                "tool.type": "orchestra_tool",
                "code.function": fn.__name__,
            })
            try:
                result = await fn(*args, **kwargs)
                t.add_event(span, "tool.complete", {"tool.name": tool_name})
                t.end_span(span, status=SpanStatus.OK)
                return result
            except Exception as exc:
                t.add_event(span, "tool.error", {
                    "tool.name": tool_name,
                    "error.message": str(exc),
                })
                t.end_span(span, status=SpanStatus.ERROR, error=str(exc))
                raise

        return wrapper
    return decorator
