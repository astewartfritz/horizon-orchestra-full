"""OpenTelemetry-compatible observability layer for Orchestra.

Enable with environment variables:
    OTEL_ENABLED=true
    OTEL_SERVICE_NAME=orchestra
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    OTEL_METRICS_EXPORTER=otlp
    OTEL_TRACES_EXPORTER=otlp
    OTEL_LOGS_EXPORTER=otlp

Sends metrics/traces/logs to an OTLP collector (Grafana Alloy, OpenTelemetry Collector,
or vendor endpoint) which forwards to Mimir/Prometheus, Tempo, and Loki.
"""

from __future__ import annotations

import os
from typing import Any

# ── Configuration ──────────────────────────────────────────────

OTEL_ENABLED = os.environ.get("OTEL_ENABLED", "").lower() in ("1", "true", "yes")
OTEL_SERVICE_NAME = os.environ.get("OTEL_SERVICE_NAME", "orchestra")
OTEL_ENDPOINT = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
OTEL_INSECURE = os.environ.get("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() in ("1", "true")
OTEL_METRICS_INTERVAL = int(os.environ.get("OTEL_METRICS_INTERVAL", "30"))

# ── Lazy init ─────────────────────────────────────────────────

_METER_PROVIDER: Any = None
_TRACER_PROVIDER: Any = None
_LOGGER_PROVIDER: Any = None
_METER: Any = None
_TRACER: Any = None
_LOGGER: Any = None


def _init_otlp() -> None:
    """Initialize OTLP exporters once."""
    global _METER_PROVIDER, _TRACER_PROVIDER, _LOGGER_PROVIDER, _METER, _TRACER, _LOGGER
    if _METER_PROVIDER is not None or not OTEL_ENABLED:
        return

    try:
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk._logs import LoggerProvider
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry import metrics, trace, _logs
    except ImportError:
        return

    resource = Resource.create({"service.name": OTEL_SERVICE_NAME})

    # Metrics
    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=OTEL_ENDPOINT, insecure=OTEL_INSECURE),
        export_interval_millis=OTEL_METRICS_INTERVAL * 1000,
    )
    _METER_PROVIDER = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(_METER_PROVIDER)
    _METER = metrics.get_meter(OTEL_SERVICE_NAME)

    # Traces
    _TRACER_PROVIDER = TracerProvider(resource=resource)
    span_processor = BatchSpanProcessor(OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=OTEL_INSECURE))
    _TRACER_PROVIDER.add_span_processor(span_processor)
    trace.set_tracer_provider(_TRACER_PROVIDER)
    _TRACER = trace.get_tracer(OTEL_SERVICE_NAME)

    # Logs
    _LOGGER_PROVIDER = LoggerProvider(resource=resource)
    log_processor = BatchLogRecordProcessor(OTLPLogExporter(endpoint=OTEL_ENDPOINT, insecure=OTEL_INSECURE))
    _LOGGER_PROVIDER.add_log_record_processor(log_processor)
    _logs.set_logger_provider(_LOGGER_PROVIDER)
    _LOGGER = _logs.getLogger(OTEL_SERVICE_NAME)


# ── Model telemetry ────────────────────────────────────────────

COST_PER_1K_TOKENS = {
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "nemotron-mini": {"input": 0.0, "output": 0.0},  # local
    "qwen2.5:7b": {"input": 0.0, "output": 0.0},     # local
    "deepseek-r1:8b": {"input": 0.0, "output": 0.0}, # local
}


def record_llm_call(model: str, prompt_tokens: int = 0, completion_tokens: int = 0,
                    cached_tokens: int = 0, latency: float = 0.0, status: str = "ok",
                    session_id: str = "") -> dict[str, float]:
    """Record an LLM call with token counts and cost. Returns cost breakdown."""
    if not OTEL_ENABLED:
        _init_otlp()
    cost_rates = COST_PER_1K_TOKENS.get(model, {"input": 0.0, "output": 0.0})
    cost_input = (prompt_tokens / 1000) * cost_rates["input"]
    cost_output = (completion_tokens / 1000) * cost_rates["output"]
    total_cost = cost_input + cost_output
    if _METER:
        try:
            # Token counters
            _METER.create_counter("llm.tokens.input").add(prompt_tokens, {"model": model, "session": session_id})
            _METER.create_counter("llm.tokens.output").add(completion_tokens, {"model": model, "session": session_id})
            _METER.create_counter("llm.tokens.cache_read").add(cached_tokens, {"model": model})
            _METER.create_counter("llm.call_count").add(1, {"model": model, "status": status})
            # Cost counter (USD)
            _METER.create_counter("llm.cost_usd", unit="USD").add(total_cost, {"model": model, "session": session_id})
            # Latency histogram
            _METER.create_histogram("llm.latency_seconds", unit="s").record(latency, {"model": model, "status": status})
        except Exception:
            pass
    return {
        "cost_input": round(cost_input, 6),
        "cost_output": round(cost_output, 6),
        "cost_total": round(total_cost, 6),
        "tokens_input": prompt_tokens,
        "tokens_output": completion_tokens,
        "tokens_cached": cached_tokens,
    }


def record_tool_call(tool: str, duration: float = 0.0, status: str = "ok",
                     accepted: bool = True, lines_changed: int = 0,
                     session_id: str = "") -> None:
    """Record a tool invocation with latency and outcome."""
    if not OTEL_ENABLED:
        return
    if _METER:
        try:
            _METER.create_counter("tool.call_count").add(1, {"tool": tool, "status": status})
            _METER.create_counter("tool.rejected").add(0 if accepted else 1, {"tool": tool})
            _METER.create_histogram("tool.latency_seconds", unit="s").record(duration, {"tool": tool, "status": status})
            if lines_changed:
                _METER.create_counter("tool.lines_changed").add(lines_changed, {"tool": tool})
        except Exception:
            pass


def record_cache(hit: bool = False, model: str = "") -> None:
    """Record cache hit/miss."""
    if not OTEL_ENABLED:
        return
    if _METER:
        try:
            _METER.create_counter("cache.access").add(1, {"model": model, "result": "hit" if hit else "miss"})
        except Exception:
            pass


def record_commit(lines_changed: int = 0, files_changed: int = 0) -> None:
    """Record a git commit."""
    if not OTEL_ENABLED:
        return
    if _METER:
        try:
            _METER.create_counter("code.commits").add(1)
            _METER.create_counter("code.lines_changed").add(lines_changed)
            _METER.create_counter("code.files_changed").add(files_changed)
        except Exception:
            pass


def record_session(session_id: str, total_cost: float = 0.0, turns: int = 0,
                   tools_used: int = 0, status: str = "ok") -> None:
    """Record session-level telemetry."""
    if not OTEL_ENABLED:
        return
    if _METER:
        try:
            _METER.create_counter("session.count").add(1, {"status": status})
            _METER.create_counter("session.turns").add(turns, {"session": session_id})
            _METER.create_counter("session.tools_used").add(tools_used, {"session": session_id})
            _METER.create_histogram("session.cost_usd", unit="USD").record(total_cost, {"session": session_id, "status": status})
        except Exception:
            pass


def get_tracer():
    """Get the OTel tracer for creating spans."""
    if not OTEL_ENABLED:
        return None
    _init_otlp()
    return _TRACER


def shutdown() -> None:
    """Flush and shut down all OTel providers."""
    global _METER_PROVIDER, _TRACER_PROVIDER, _LOGGER_PROVIDER
    if _METER_PROVIDER:
        try:
            _METER_PROVIDER.shutdown()
        except Exception:
            pass
    if _TRACER_PROVIDER:
        try:
            _TRACER_PROVIDER.shutdown()
        except Exception:
            pass
    if _LOGGER_PROVIDER:
        try:
            _LOGGER_PROVIDER.shutdown()
        except Exception:
            pass
