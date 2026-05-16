"""Complete Jaeger tracing pipeline — OTel → Tempo → Jaeger → Grafana."""

from __future__ import annotations

from code_agent.tracing.jaeger import JaegerTracer, configure_jaeger, get_jaeger_tracer
from code_agent.tracing.instrumentation import TracingMiddleware, instrument_fastapi, instrument_httpx
from code_agent.tracing.propagator import TracePropagator, inject_traceparent, extract_traceparent
from code_agent.tracing.bridge import AgentTracerBridge

__all__ = [
    "JaegerTracer", "configure_jaeger", "get_jaeger_tracer",
    "TracingMiddleware", "instrument_fastapi", "instrument_httpx",
    "TracePropagator", "inject_traceparent", "extract_traceparent",
    "AgentTracerBridge",
]
