"""Jaeger tracer — OTel spans exported to Jaeger via gRPC or HTTP."""

from __future__ import annotations

import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Generator

from code_agent.telemetry.otel import OTEL_ENABLED, OTEL_ENDPOINT, _init_otlp, _TRACER


@dataclass
class SpanContext:
    trace_id: str
    span_id: str
    is_remote: bool = False

    @property
    def trace_flags(self) -> int:
        return 1  # sampled


@dataclass
class Span:
    """Represents a single span in the trace tree."""
    name: str
    context: SpanContext
    parent_id: str = ""
    kind: str = "internal"  # internal, server, client, producer, consumer
    start_time: float = 0.0
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    status: str = "ok"  # ok, error, unset
    status_message: str = ""

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    def add_event(self, name: str, attributes: dict[str, Any] = None) -> None:
        self.events.append({
            "name": name,
            "attributes": attributes or {},
            "timestamp": time.time(),
        })

    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000 if self.end_time > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.context.trace_id,
            "span_id": self.context.span_id,
            "parent_span_id": self.parent_id,
            "name": self.name,
            "kind": self.kind,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms(),
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
            "status_message": self.status_message,
        }


class JaegerTracer:
    """Tracer that creates spans and exports them to Jaeger via OTel.

    Usage:
        tracer = JaegerTracer(service_name="orchestra-api")
        with tracer.start_span("handle_request") as span:
            span.set_attribute("http.method", "POST")
            with tracer.start_span("llm_call") as child:
                child.set_attribute("llm.model", "gpt-4o")
    """

    def __init__(self, service_name: str = "orchestra", use_otel: bool = True):
        self.service_name = service_name
        self.use_otel = use_otel and OTEL_ENABLED
        self._spans: dict[str, Span] = {}
        self._active_span_ids: dict[str, str] = {}  # trace_id → current span_id

    # ── Span creation ─────────────────────────────────────────

    def start_span(self, name: str, parent: Span | None = None,
                   kind: str = "internal",
                   attributes: dict[str, Any] = None) -> Span:
        """Create and start a new span. If parent is None, creates a root span."""
        trace_id = parent.context.trace_id if parent else uuid.uuid4().hex
        span_id = uuid.uuid4().hex[:16]
        parent_id = parent.context.span_id if parent else ""

        ctx = SpanContext(trace_id=trace_id, span_id=span_id)
        span = Span(
            name=name,
            context=ctx,
            parent_id=parent_id,
            kind=kind,
            start_time=time.time(),
            attributes=attributes or {},
        )
        self._spans[span_id] = span
        self._active_span_ids[trace_id] = span_id
        return span

    def end_span(self, span: Span, status: str = "ok", message: str = "") -> None:
        """End a span and export it."""
        span.end_time = time.time()
        span.status = status
        span.status_message = message
        self._export_span(span)

    @contextmanager
    def start_active_span(self, name: str, kind: str = "internal",
                          attributes: dict[str, Any] = None) -> Generator[Span, None, None]:
        """Context manager: starts a span, sets it as active, ends on exit."""
        parent = self._get_active_span()
        span = self.start_span(name, parent=parent, kind=kind, attributes=attributes)
        try:
            yield span
        except Exception as e:
            self.end_span(span, status="error", message=str(e))
            raise
        else:
            self.end_span(span)

    # ── Span retrieval ────────────────────────────────────────

    def _get_active_span(self) -> Span | None:
        """Get the currently active span (most recently started)."""
        # Return the most recently started span
        sorted_spans = sorted(
            self._spans.values(),
            key=lambda s: s.start_time,
            reverse=True,
        )
        for span in sorted_spans:
            if span.end_time == 0:  # still active
                return span
        return None

    def get_span(self, span_id: str) -> Span | None:
        return self._spans.get(span_id)

    def get_trace_spans(self, trace_id: str) -> list[Span]:
        return [s for s in self._spans.values() if s.context.trace_id == trace_id]

    # ── Export ─────────────────────────────────────────────────

    def _export_span(self, span: Span) -> None:
        """Export a span — via OTel if enabled, otherwise store in memory."""
        if self.use_otel and _TRACER:
            try:
                self._export_via_otel(span)
                return
            except Exception:
                pass
        # Fallback: keep in memory for Jaeger UI query
        self._spans[span.context.span_id] = span

    def _export_via_otel(self, span: Span) -> None:
        """Export span using the OTel tracer provider."""
        if not _TRACER:
            return
        attrs = {}
        for k, v in span.attributes.items():
            if isinstance(v, (str, bool, int, float)):
                attrs[k] = v

        # OTel expects trace_id/span_id as bytes
        trace_bytes = bytes.fromhex(span.context.trace_id) if len(span.context.trace_id) == 32 else None

        with _TRACER.start_as_current_span(
            span.name,
            kind=1,  # SpanKind.INTERNAL
            attributes=attrs,
        ) as otel_span:
            for event in span.events:
                otel_span.add_event(event["name"], event.get("attributes", {}))
            if span.status == "error":
                otel_span.set_status(1, span.status_message)  # StatusCode.ERROR

    # ─── Query ─────────────────────────────────────────────────

    def find_traces(self, service: str = "", operation: str = "",
                    limit: int = 20, tags: dict[str, str] = None) -> list[dict[str, Any]]:
        """Find traces by service, operation, or tags. Returns trace summaries."""
        tags = tags or {}
        traces: dict[str, list[Span]] = {}

        for span in self._spans.values():
            if service and service not in str(span.attributes.get("service.name", "")):
                continue
            if operation and operation != span.name:
                continue
            if tags and not all(
                str(span.attributes.get(k)) == v for k, v in tags.items()
            ):
                continue
            traces.setdefault(span.context.trace_id, []).append(span)

        result = []
        for trace_id, spans in traces.items():
            root = next((s for s in spans if not s.parent_id), spans[0])
            result.append({
                "trace_id": trace_id,
                "root_name": root.name,
                "root_service": root.attributes.get("service.name", ""),
                "span_count": len(spans),
                "duration_ms": root.duration_ms(),
                "start_time": root.start_time,
                "errors": sum(1 for s in spans if s.status == "error"),
            })

        result.sort(key=lambda t: t["start_time"], reverse=True)
        return result[:limit]

    def get_trace_detail(self, trace_id: str) -> list[dict[str, Any]]:
        """Return all spans for a trace as dicts."""
        spans = self.get_trace_spans(trace_id)
        return [s.to_dict() for s in sorted(spans, key=lambda s: s.start_time)]

    # ── Stats ──────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        all_spans = list(self._spans.values())
        trace_ids = set(s.context.trace_id for s in all_spans)
        return {
            "total_spans": len(all_spans),
            "total_traces": len(trace_ids),
            "active_spans": sum(1 for s in all_spans if s.end_time == 0),
            "error_spans": sum(1 for s in all_spans if s.status == "error"),
            "service": self.service_name,
            "otel_enabled": self.use_otel,
        }


# ── Module-level singleton ────────────────────────────────

_GLOBAL_TRACER: JaegerTracer | None = None


def configure_jaeger(service_name: str = "orchestra", otel_endpoint: str = "") -> JaegerTracer:
    """Configure and return the global JaegerTracer singleton."""
    global _GLOBAL_TRACER
    if otel_endpoint:
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = otel_endpoint
    if not os.environ.get("OTEL_ENABLED"):
        os.environ["OTEL_ENABLED"] = "true"
    _init_otlp()
    _GLOBAL_TRACER = JaegerTracer(service_name=service_name)
    return _GLOBAL_TRACER


def get_jaeger_tracer() -> JaegerTracer:
    """Get the global JaegerTracer singleton, creating it if needed."""
    global _GLOBAL_TRACER
    if _GLOBAL_TRACER is None:
        _GLOBAL_TRACER = JaegerTracer()
    return _GLOBAL_TRACER
