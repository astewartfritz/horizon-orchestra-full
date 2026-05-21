"""Auto-instrumentation middleware for FastAPI, httpx, and LLM calls."""

from __future__ import annotations

import time
import uuid
from typing import Any, Callable

from fastapi import FastAPI, Request, Response

from orchestra.code_agent.tracing.jaeger import JaegerTracer, get_jaeger_tracer
from orchestra.code_agent.tracing.propagator import extract_traceparent, inject_traceparent


class TracingMiddleware:
    """FastAPI middleware that traces every HTTP request.

    Adds:
      - Span per request with method, path, status, duration
      - W3C traceparent header propagation
      - Trace ID in response headers (x-trace-id)
    """

    def __init__(self, app: FastAPI, tracer: JaegerTracer | None = None,
                 exclude_paths: set[str] | None = None):
        self.app = app
        self.tracer = tracer or get_jaeger_tracer()
        self.exclude_paths = exclude_paths or {"/health", "/metrics", "/favicon.ico"}

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path in self.exclude_paths:
            return await call_next(request)

        method = request.method

        # Extract or create trace context
        traceparent = request.headers.get("traceparent", "")
        attributes = {
            "http.method": method,
            "http.url": str(request.url),
            "http.path": path,
            "service.name": "orchestra",
        }

        # Start span
        span_name = f"{method} {path}"
        span = self.tracer.start_span(span_name, kind="server", attributes=attributes)
        trace_id = span.context.trace_id

        start = time.time()

        try:
            response = await call_next(request)
            elapsed = time.time() - start
            span.set_attribute("http.status_code", response.status_code)
            span.set_attribute("http.duration_ms", round(elapsed * 1000, 2))
            self.tracer.end_span(span)
            response.headers["x-trace-id"] = trace_id
            if not traceparent:
                response.headers["traceparent"] = inject_traceparent(
                    trace_id, span.context.span_id,
                )
            return response
        except Exception as e:
            elapsed = time.time() - start
            span.set_attribute("http.status_code", 500)
            span.set_attribute("http.duration_ms", round(elapsed * 1000, 2))
            self.tracer.end_span(span, status="error", message=str(e))
            raise


def instrument_fastapi(app: FastAPI, tracer: JaegerTracer | None = None,
                       exclude_paths: set[str] | None = None) -> None:
    """Add tracing middleware to a FastAPI application."""
    middleware = TracingMiddleware(app, tracer, exclude_paths)
    app.middleware("http")(middleware)


def instrument_httpx(tracer: JaegerTracer | None = None) -> None:
    """Patch httpx to add distributed tracing to outgoing requests.

    Adds span per HTTP call with method, URL, status, and traceparent header.
    """
    import httpx

    _original_send = httpx.AsyncClient.send

    tracer = tracer or get_jaeger_tracer()

    async def traced_send(self: httpx.AsyncClient, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        span = tracer.start_span(
            f"HTTP {request.method} {request.url.path}",
            kind="client",
            attributes={
                "http.method": request.method,
                "http.url": str(request.url),
                "service.name": "orchestra",
            },
        )
        # Inject trace context into outgoing request
        request.headers["traceparent"] = inject_traceparent(
            span.context.trace_id, span.context.span_id,
        )
        try:
            response = await _original_send(self, request, **kwargs)
            span.set_attribute("http.status_code", response.status_code)
            tracer.end_span(span)
            return response
        except Exception as e:
            tracer.end_span(span, status="error", message=str(e))
            raise

    httpx.AsyncClient.send = traced_send  # type: ignore


# ── LLM Call tracing ──────────────────────────────────

def trace_llm_call(tracer: JaegerTracer | None = None):
    """Decorator to trace LLM provider calls with detailed attributes.

    Usage:
        @trace_llm_call()
        async def call_llm(prompt, model="gpt-4o"):
            ...
    """
    tracer = tracer or get_jaeger_tracer()

    def decorator(func: Callable) -> Callable:
        import functools

        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            model = kwargs.get("model", kwargs.get("model_name", "unknown"))
            span = tracer.start_span(
                f"llm.{model}",
                kind="client",
                attributes={
                    "llm.model": model,
                    "llm.provider": kwargs.get("provider", ""),
                    "llm.temperature": str(kwargs.get("temperature", "")),
                    "service.name": "orchestra",
                },
            )
            start = time.time()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.time() - start
                span.set_attribute("llm.latency_seconds", round(elapsed, 3))
                # Extract token usage from result if available
                if hasattr(result, "usage"):
                    usage = result.usage
                    span.set_attribute("llm.prompt_tokens", getattr(usage, "prompt_tokens", 0))
                    span.set_attribute("llm.completion_tokens", getattr(usage, "completion_tokens", 0))
                tracer.end_span(span)
                return result
            except Exception as e:
                elapsed = time.time() - start
                span.set_attribute("llm.latency_seconds", round(elapsed, 3))
                tracer.end_span(span, status="error", message=str(e))
                raise

        return wrapper
    return decorator
