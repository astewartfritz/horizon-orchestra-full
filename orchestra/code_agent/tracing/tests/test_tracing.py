"""Tests for the Jaeger tracing pipeline."""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request, Response

from orchestra.code_agent.telemetry.tracer import AgentTracer, TraceSpan
from orchestra.code_agent.tracing.bridge import AgentTracerBridge
from orchestra.code_agent.tracing.instrumentation import (
    TracingMiddleware,
    instrument_fastapi,
    instrument_httpx,
    trace_llm_call,
)
from orchestra.code_agent.tracing.jaeger import (
    JaegerTracer,
    Span,
    SpanContext,
    configure_jaeger,
    get_jaeger_tracer,
)
from orchestra.code_agent.tracing.propagator import (
    TracePropagator,
    extract_traceparent,
    extract_tracestate,
    inject_traceparent,
    inject_tracestate,
)


# ── Span Model ─────────────────────────────────

class TestSpan:
    def test_creates_span_with_context(self):
        ctx = SpanContext(trace_id="abc", span_id="def")
        span = Span(name="test", context=ctx)
        assert span.name == "test"
        assert span.context.trace_id == "abc"

    def test_set_attribute(self):
        span = Span("test", SpanContext("t1", "s1"))
        span.set_attribute("model", "gpt-4o")
        assert span.attributes["model"] == "gpt-4o"

    def test_add_event(self):
        span = Span("test", SpanContext("t", "s"))
        span.add_event("llm.start", {"tokens": 100})
        assert len(span.events) == 1

    def test_duration_ms_zero_if_not_ended(self):
        assert Span("test", SpanContext("t", "s")).duration_ms() == 0.0

    def test_duration_ms_after_end(self):
        span = Span("test", SpanContext("t", "s"), start_time=100.0, end_time=102.5)
        assert span.duration_ms() == 2500.0

    def test_to_dict_contains_all_keys(self):
        span = Span("op", SpanContext("t1", "s1"), parent_id="p1", kind="server")
        span.set_attribute("key", "val")
        d = span.to_dict()
        assert d["name"] == "op"
        assert d["parent_span_id"] == "p1"
        assert d["attributes"]["key"] == "val"


# ── JaegerTracer ───────────────────────────────

class TestJaegerTracer:
    def test_start_span_creates_root(self):
        tracer = JaegerTracer(use_otel=False)
        span = tracer.start_span("root")
        assert span.name == "root"
        assert span.parent_id == ""
        assert len(span.context.trace_id) == 32

    def test_start_span_with_parent(self):
        tracer = JaegerTracer(use_otel=False)
        parent = tracer.start_span("parent")
        child = tracer.start_span("child", parent=parent)
        assert child.parent_id == parent.context.span_id

    def test_end_span_sets_end_time(self):
        tracer = JaegerTracer(use_otel=False)
        span = tracer.start_span("test")
        tracer.end_span(span)
        assert span.end_time > 0

    def test_end_span_with_error(self):
        tracer = JaegerTracer(use_otel=False)
        span = tracer.start_span("test")
        tracer.end_span(span, status="error", message="timeout")
        assert span.status == "error"
        assert span.status_message == "timeout"

    def test_start_active_span(self):
        tracer = JaegerTracer(use_otel=False)
        with tracer.start_active_span("op", attributes={"k": "v"}) as span:
            assert span.name == "op"
            assert span.attributes["k"] == "v"
        assert span.end_time > 0

    def test_start_active_span_marks_error(self):
        tracer = JaegerTracer(use_otel=False)
        with pytest.raises(ValueError):
            with tracer.start_active_span("fail"):
                raise ValueError("boom")
        error_spans = [s for s in tracer._spans.values() if s.status == "error"]
        assert len(error_spans) == 1

    def test_get_span_by_id(self):
        tracer = JaegerTracer(use_otel=False)
        span = tracer.start_span("test")
        assert tracer.get_span(span.context.span_id) is span

    def test_get_trace_spans(self):
        tracer = JaegerTracer(use_otel=False)
        root = tracer.start_span("root")
        tracer.start_span("child", parent=root)
        assert len(tracer.get_trace_spans(root.context.trace_id)) == 2

    def test_find_traces_by_service(self):
        tracer = JaegerTracer(use_otel=False)
        s = tracer.start_span("h", attributes={"service.name": "api"})
        tracer.end_span(s)
        assert len(tracer.find_traces(service="api")) >= 1

    def test_find_traces_by_operation(self):
        tracer = JaegerTracer(use_otel=False)
        s = tracer.start_span("llm_call")
        tracer.end_span(s)
        assert len(tracer.find_traces(operation="llm_call")) >= 1

    def test_find_traces_by_tags(self):
        tracer = JaegerTracer(use_otel=False)
        s = tracer.start_span("test", attributes={"model": "gpt-4"})
        tracer.end_span(s)
        assert len(tracer.find_traces(tags={"model": "gpt-4"})) >= 1

    def test_find_traces_no_match(self):
        tracer = JaegerTracer(use_otel=False)
        assert tracer.find_traces(operation="nonexistent") == []

    def test_get_trace_detail(self):
        tracer = JaegerTracer(use_otel=False)
        root = tracer.start_span("root")
        child = tracer.start_span("child", parent=root)
        tracer.end_span(child)
        tracer.end_span(root)
        detail = tracer.get_trace_detail(root.context.trace_id)
        assert len(detail) == 2

    def test_stats(self):
        tracer = JaegerTracer(use_otel=False)
        s1 = tracer.start_span("a")
        s2 = tracer.start_span("b")
        tracer.end_span(s1)
        tracer.end_span(s2, status="error")
        st = tracer.stats()
        assert st["total_spans"] == 2
        assert st["error_spans"] == 1

    def test_configure_jaeger_sets_env(self):
        with patch.dict("os.environ", {}, clear=True):
            t = configure_jaeger("test-svc")
            assert t.service_name == "test-svc"
            assert os.environ.get("OTEL_ENABLED") == "true"

    def test_get_jaeger_tracer_singleton(self):
        t1 = get_jaeger_tracer()
        t2 = get_jaeger_tracer()
        assert t1 is t2


# ── Propagator ─────────────────────────────────

class TestPropagator:
    def test_inject_traceparent_format(self):
        tp = inject_traceparent("a" * 32, "b" * 16)
        assert tp.startswith("00-")
        assert len(tp) == 55

    def test_extract_traceparent_valid(self):
        tp = inject_traceparent("a" * 32, "b" * 16)
        r = extract_traceparent(tp)
        assert r is not None
        assert r["trace_id"] == "a" * 32

    def test_extract_traceparent_invalid(self):
        assert extract_traceparent("") is None
        assert extract_traceparent("bad") is None

    def test_inject_extract_tracestate(self):
        h = inject_tracestate({"k1": "v1", "k2": "v2"})
        r = extract_tracestate(h)
        assert r["k1"] == "v1"
        assert r["k2"] == "v2"

    def test_extract_tracestate_empty(self):
        assert extract_tracestate("") == {}

    def test_propagator_roundtrip(self):
        p = TracePropagator()
        h = {"ct": "json"}
        p.inject(h, "a" * 32, "b" * 16)
        r = p.extract(h)
        assert r["trace_id"] == "a" * 32
        assert r["span_id"] == "b" * 16

    def test_propagator_empty_headers(self):
        assert TracePropagator().extract({}) == {}

    def test_format_otlp(self):
        tb, sb = TracePropagator.format_otlp("a" * 32, "b" * 16)
        assert len(tb) == 16
        assert len(sb) == 8


# ── AgentTracerBridge ──────────────────────────

class TestAgentTracerBridge:
    def test_bridge_agent_span(self):
        bridge = AgentTracerBridge(
            agent_tracer=AgentTracer(),
            jaeger_tracer=JaegerTracer(use_otel=False),
        )
        agent_span = TraceSpan(span_id="s1", name="llm_call", start_time=100.0, end_time=102.0)
        jspan = bridge.bridge_agent_span(agent_span, "trace1")
        assert jspan is not None
        assert jspan.name == "llm_call"

    def test_bridge_with_parent(self):
        bridge = AgentTracerBridge(jaeger_tracer=JaegerTracer(use_otel=False))
        parent = TraceSpan(span_id="p1", name="root")
        child = TraceSpan(span_id="c1", name="sub", parent_id="p1")
        p = bridge.bridge_agent_span(parent, "t1")
        c = bridge.bridge_agent_span(child, "t1")
        assert c is not None
        assert c.parent_id == p.context.span_id

    def test_bridge_jaeger_span(self):
        bridge = AgentTracerBridge(jaeger_tracer=JaegerTracer(use_otel=False))
        span = Span("op", SpanContext("t1", "s1"), start_time=100.0, end_time=102.0)
        ts = bridge.bridge_jaeger_span(span)
        assert ts.name == "op"

    def test_sync_all(self):
        at = AgentTracer()
        at.start_trace()
        bridge = AgentTracerBridge(agent_tracer=at, jaeger_tracer=JaegerTracer(use_otel=False))
        r = bridge.sync_all()
        assert "bridged_spans" in r

    def test_write_jaeger_spans_to_agent(self):
        jaeger = JaegerTracer(use_otel=False)
        bridge = AgentTracerBridge(jaeger_tracer=jaeger)
        s = jaeger.start_span("test_op")
        jaeger.end_span(s)
        count = bridge.write_jaeger_spans_to_agent(s.context.trace_id)
        assert count == 1


# ── Instrumentation ────────────────────────────

class TestInstrumentation:
    @pytest.mark.asyncio
    async def test_middleware_traces_requests(self):
        tracer = JaegerTracer(use_otel=False)
        mw = TracingMiddleware(MagicMock(spec=FastAPI), tracer, exclude_paths=set())

        req = MagicMock(spec=Request)
        req.url.path = "/api/chat"
        url_mock = MagicMock()
        url_mock.__str__.return_value = "http://test/api/chat"
        req.url = url_mock
        req.method = "POST"
        req.headers = {}
        req.state = MagicMock()

        resp = MagicMock(spec=Response)
        resp.status_code = 200
        resp.headers = {}

        async def call_next(r):
            return resp

        result = await mw(req, call_next)
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_middleware_excludes_paths(self):
        tracer = JaegerTracer(use_otel=False)
        mw = TracingMiddleware(MagicMock(spec=FastAPI), tracer, exclude_paths={"/health"})

        req = MagicMock(spec=Request)
        req.url.path = "/health"
        req.method = "GET"
        req.headers = {}

        async def call_next(r):
            return Response(status_code=200)

        result = await mw(req, call_next)
        assert result.status_code == 200

    def test_instrument_fastapi(self):
        # Just verify it doesn't crash
        from orchestra.code_agent.tracing.instrumentation import instrument_fastapi as ifa
        assert callable(ifa)

    @pytest.mark.asyncio
    async def test_trace_llm_call(self):
        tracer = JaegerTracer(use_otel=False)

        @trace_llm_call(tracer)
        async def call_llm(model="gpt-4o", provider="openai"):
            return {"choices": [{"text": "hello"}]}

        result = await call_llm(model="gpt-4o", provider="openai")
        assert result["choices"][0]["text"] == "hello"

    @pytest.mark.asyncio
    async def test_trace_llm_call_error(self):
        tracer = JaegerTracer(use_otel=False)

        @trace_llm_call(tracer)
        async def call_llm(**kw):
            raise RuntimeError("API error")

        with pytest.raises(RuntimeError):
            await call_llm(model="gpt-4o")
