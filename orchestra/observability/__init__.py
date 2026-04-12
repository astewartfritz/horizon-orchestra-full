"""Enterprise observability stack for Horizon Orchestra.

Provides production-grade telemetry, security event export, distributed
tracing, load testing, and automated failover runbooks — everything an
SRE team needs before trusting the platform in production.

Modules
-------
prometheus
    Prometheus-compatible metrics endpoint (pure Python, no deps).
siem
    Structured security event export (Splunk HEC, ECS, CEF, LEEF, Syslog).
tracing
    OpenTelemetry-compatible distributed tracing (Jaeger, Zipkin, OTLP).
load_test
    Built-in asyncio load-testing harness with SLA assertions.
runbooks
    Self-executing automated failover runbooks.
"""

from __future__ import annotations

from .prometheus import (
    Counter,
    Gauge,
    Histogram,
    Metric,
    MetricType,
    MetricsMiddleware,
    PrometheusRegistry,
    ORCHESTRA_METRICS,
)
from .siem import (
    SIEMEvent,
    SIEMExporter,
    SIEMFormat,
    ORCHESTRA_EVENT_TYPES,
)
from .tracing import (
    OrchestraTracer,
    Span,
    SpanStatus,
    TraceContext,
    traced,
    traced_tool,
)
from .load_test import (
    LoadTestConfig,
    LoadTestResult,
    LoadTestScenario,
    OrchestraLoadTester,
    api_chat_scenario,
    api_stream_scenario,
    concurrent_agents_scenario,
)
from .runbooks import (
    Runbook,
    RunbookExecutor,
    RunbookResult,
    RunbookStep,
    PREBUILT_RUNBOOKS,
)

__all__ = [
    # prometheus
    "Counter",
    "Gauge",
    "Histogram",
    "Metric",
    "MetricType",
    "MetricsMiddleware",
    "PrometheusRegistry",
    "ORCHESTRA_METRICS",
    # siem
    "SIEMEvent",
    "SIEMExporter",
    "SIEMFormat",
    "ORCHESTRA_EVENT_TYPES",
    # tracing
    "OrchestraTracer",
    "Span",
    "SpanStatus",
    "TraceContext",
    "traced",
    "traced_tool",
    # load_test
    "LoadTestConfig",
    "LoadTestResult",
    "LoadTestScenario",
    "OrchestraLoadTester",
    "api_chat_scenario",
    "api_stream_scenario",
    "concurrent_agents_scenario",
    # runbooks
    "Runbook",
    "RunbookExecutor",
    "RunbookResult",
    "RunbookStep",
    "PREBUILT_RUNBOOKS",
]
