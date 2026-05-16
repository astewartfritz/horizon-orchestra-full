from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class TraceSpan:
    span_id: str
    parent_id: str = ""
    name: str = ""
    start_time: float = 0.0
    end_time: float = 0.0
    attributes: dict[str, Any] = field(default_factory=dict)
    status: str = "ok"

    def duration_ms(self) -> float:
        return (self.end_time - self.start_time) * 1000


@dataclass
class TraceContext:
    trace_id: str
    spans: list[TraceSpan] = field(default_factory=list)
    active_span_id: str = ""


class AgentTracer:
    _instance: AgentTracer | None = None
    _lock = threading.Lock()

    def __init__(self, output_path: str = ".agent-traces.jsonl"):
        self.path = Path(output_path)
        self._contexts: dict[str, TraceContext] = {}

    @classmethod
    def get(cls) -> AgentTracer:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start_trace(self) -> str:
        trace_id = str(uuid.uuid4())[:8]
        self._contexts[trace_id] = TraceContext(trace_id=trace_id)
        return trace_id

    def start_span(self, trace_id: str, name: str, parent_id: str = "", attributes: dict[str, Any] | None = None) -> str:
        ctx = self._contexts.get(trace_id)
        if not ctx:
            return ""

        span_id = str(uuid.uuid4())[:8]
        span = TraceSpan(
            span_id=span_id,
            parent_id=parent_id or ctx.active_span_id,
            name=name,
            start_time=time.time(),
            attributes=attributes or {},
        )
        ctx.spans.append(span)
        ctx.active_span_id = span_id
        return span_id

    def end_span(self, trace_id: str, span_id: str, status: str = "ok") -> None:
        ctx = self._contexts.get(trace_id)
        if not ctx:
            return
        for span in ctx.spans:
            if span.span_id == span_id:
                span.end_time = time.time()
                span.status = status
                ctx.active_span_id = span.parent_id
                self._write_span(trace_id, span)
                break

    def _write_span(self, trace_id: str, span: TraceSpan) -> None:
        entry = {"trace_id": trace_id, **asdict(span)}
        try:
            with open(self.path, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    def get_trace(self, trace_id: str) -> TraceContext | None:
        return self._contexts.get(trace_id)

    def summary(self, trace_id: str) -> dict[str, Any]:
        ctx = self._contexts.get(trace_id)
        if not ctx:
            return {}
        total_ms = sum(s.duration_ms() for s in ctx.spans if s.end_time > 0)
        return {
            "trace_id": trace_id,
            "spans": len(ctx.spans),
            "total_duration_ms": round(total_ms, 2),
            "errors": sum(1 for s in ctx.spans if s.status == "error"),
        }


class traced:
    """Decorator to trace async function calls."""

    def __init__(self, name: str = "", attributes: dict[str, Any] = None):
        self.name = name
        self.attributes = attributes or {}

    def __call__(self, func):
        import functools

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            tracer = AgentTracer.get()
            trace_id = tracer.start_trace()
            span_id = tracer.start_span(trace_id, self.name or func.__name__, attributes=self.attributes)
            try:
                result = await func(*args, **kwargs)
                tracer.end_span(trace_id, span_id, "ok")
                return result
            except Exception as e:
                tracer.end_span(trace_id, span_id, "error")
                raise

        return wrapper
