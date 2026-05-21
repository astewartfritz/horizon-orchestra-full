"""Bridge between AgentTracer (file-based) and OTel/Jaeger spans."""

from __future__ import annotations

import time
from typing import Any

from orchestra.code_agent.telemetry.tracer import AgentTracer, TraceSpan
from orchestra.code_agent.tracing.jaeger import JaegerTracer, Span, SpanContext
from orchestra.code_agent.tracing.propagator import generate_span_id, generate_trace_id


class AgentTracerBridge:
    """Bidirectionally bridges AgentTracer spans with OTel/Jaeger spans.

    - AgentSpan → OTelSpan: reads AgentTracer's .agent-traces.jsonl
      and creates corresponding Jaeger/OTel spans
    - OTelSpan → AgentSpan: creates AgentTracer spans from current Jaeger spans
    """

    def __init__(self, agent_tracer: AgentTracer | None = None,
                 jaeger_tracer: JaegerTracer | None = None):
        self.agent_tracer = agent_tracer or AgentTracer.get()
        self.jaeger_tracer = jaeger_tracer or JaegerTracer()
        self._span_map: dict[str, str] = {}  # agent_span_id → jaeger_span_id

    # ── AgentTracer → Jaeger ─────────────────────────────────

    def bridge_agent_span(self, agent_span: TraceSpan, trace_id: str = "") -> Span | None:
        """Convert an AgentTracer TraceSpan into a Jaeger Span."""
        if not trace_id:
            trace_id = generate_trace_id()

        jaeger_span_id = generate_span_id()
        parent_id = ""
        if agent_span.parent_id:
            parent_id = self._span_map.get(agent_span.parent_id, "")

        ctx = SpanContext(trace_id=trace_id, span_id=jaeger_span_id)
        span = Span(
            name=agent_span.name,
            context=ctx,
            parent_id=parent_id,
            start_time=agent_span.start_time,
            end_time=agent_span.end_time or time.time(),
            attributes=dict(agent_span.attributes),
            status=agent_span.status,
        )
        self._span_map[agent_span.span_id] = jaeger_span_id
        return span

    def bridge_all_agent_spans(self, trace_id: str = "") -> list[Span]:
        """Convert all pending AgentTracer spans to Jaeger spans."""
        if not trace_id:
            trace_id = generate_trace_id()

        # Read traces from AgentTracer
        # AgentTracer stores them in memory in _contexts
        spans = []
        for ctx in self.agent_tracer._contexts.values():
            for agent_span in ctx.spans:
                span = self.bridge_agent_span(agent_span, trace_id)
                if span:
                    spans.append(span)
        return spans

    def sync_all(self) -> dict[str, Any]:
        """Sync all AgentTracer spans to Jaeger, return summary."""
        spans = self.bridge_all_agent_spans()
        trace_ids = set(s.context.trace_id for s in spans)
        return {
            "bridged_spans": len(spans),
            "traces_created": len(trace_ids),
            "trace_ids": list(trace_ids),
        }

    # ── Jaeger → AgentTracer ─────────────────────────────────

    def bridge_jaeger_span(self, span: Span) -> TraceSpan:
        """Convert a Jaeger Span back to an AgentTracer TraceSpan."""
        agent_span_id = generate_span_id()[:8]
        trace_span = TraceSpan(
            span_id=agent_span_id,
            parent_id=span.parent_id[:8] if span.parent_id else "",
            name=span.name,
            start_time=span.start_time,
            end_time=span.end_time,
            attributes=dict(span.attributes),
            status=span.status,
        )
        return trace_span

    def write_jaeger_spans_to_agent(self, trace_id: str) -> int:
        """Write all Jaeger spans for a trace to AgentTracer's storage."""
        spans = self.jaeger_tracer.get_trace_spans(trace_id)
        for span in spans:
            trace_span = self.bridge_jaeger_span(span)
            # Write to AgentTracer's file
            self.agent_tracer._write_span(trace_id, trace_span)
        return len(spans)
