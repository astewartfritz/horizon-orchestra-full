# Tracing Pipeline — OTel → Tempo → Jaeger → Grafana

> **Modules:** `src/code_agent/tracing/` (40 tests) + `tracing/tempo/` (Docker Compose)

End-to-end distributed tracing pipeline using OpenTelemetry for instrumentation, Tempo for storage, Jaeger for querying, and Grafana for visualization.

---

## Pipeline

```
Application (Python SDK)
  │ OTLP gRPC/HTTP
  ▼
OpenTelemetry Collector
  │ batch + attributes + resource detection
  ▼
Tempo (distributed trace store)
  │ 48h retention • local backend • OTLP ingest
  ▼
Jaeger Query UI (http://localhost:16686)
Grafana (http://localhost:3000, admin/admin)
```

## Start the Stack

```bash
docker compose -f tracing/tempo/docker-compose.yaml up -d
```

### Services

| Service | Port | Purpose |
|---------|------|---------|
| Tempo | 3200, 4317, 4318 | Trace storage + OTLP ingest |
| Jaeger Query | 16686 | Trace viewer UI |
| Jaeger Collector | 14250, 14268 | Alternative ingest |
| Grafana | 3000 | Dashboards |
| OTel Collector | 4317, 4318 | OTLP → Tempo relay |

---

## Module: `jaeger.py`

`JaegerTracer` — span creation, export, and query.

```python
tracer = JaegerTracer(service_name="orchestra-api")

# Manual tracing
span = tracer.start_span("process_order", attributes={"order_id": "123"})
# ... do work ...
tracer.end_span(span)

# Context manager (auto end)
with tracer.start_active_span("llm_call", attributes={"model": "gpt-4o"}) as span:
    span.add_event("tokens", {"prompt": 500})
    result = await call_llm()
    span.set_attribute("latency_ms", 1200)

# Query
tracer.find_traces(service="orchestra", operation="llm_call", tags={"model": "gpt-4o"})
tracer.get_trace_detail(trace_id)
tracer.stats()  # total/active/error spans
```

## Module: `instrumentation.py`

Auto-instrumentation for FastAPI, httpx, and LLM calls.

```python
from code_agent.tracing.instrumentation import instrument_fastapi, trace_llm_call

instrument_fastapi(app)  # auto-traces all HTTP requests

@trace_llm_call()
async def call_llm(prompt, model="gpt-4o"):
    return await provider.complete(prompt)
```

### TracingMiddleware
- Traces every HTTP request with method/path/status/duration
- Injects `x-trace-id` + `traceparent` (W3C) in response headers
- Excludes `/health`, `/metrics`, `/favicon.ico`

### instrument_httpx
- Monkey-patches `httpx.AsyncClient.send` to auto-trace outgoing HTTP
- Propagates trace context via `traceparent` header

## Module: `propagator.py`

W3C trace context propagation.

```python
# Inject
header = inject_traceparent(trace_id, span_id, sampled=True)
# "00-abc...def-123...789-01"

# Extract
ctx = extract_traceparent(header)
# {"trace_id": "...", "span_id": "...", "flags": "01"}

# Tracestate
tracestate = inject_tracestate({"vendor": "specific=data"})
parsed = extract_tracestate(tracestate)
```

## Module: `bridge.py`

Bidirectional bridge between `AgentTracer` (file-based JSONL) and OTel/Jaeger.

```python
bridge = AgentTracerBridge()
# AgentTracer → Jaeger
bridge.bridge_all_agent_spans()
bridge.sync_all()

# Jaeger → AgentTracer
bridge.write_jaeger_spans_to_agent(trace_id)
```

## Docker Compose Files

| File | Purpose |
|------|---------|
| `docker-compose.yaml` | 5 services: tempo, jaeger, jaeger-collector, grafana, otel-collector |
| `tempo.yaml` | Tempo config: OTLP ingest, local storage, 48h retention, metrics generator |
| `grafana-datasources.yaml` | Auto-provisioned: Tempo, Jaeger, Prometheus, Loki |
| `otel-collector.yaml` | Pipeline: OTLP → batch → attributes → Tempo + Prometheus |

## Configuration

Environment variables:
```bash
OTEL_ENABLED=true
OTEL_SERVICE_NAME=orchestra
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
```

## Test Coverage (40 tests)

- Span: creation, attributes, events, duration, serialization
- JaegerTracer: root/parent spans, end (ok/error), context manager, error marking, get by ID, trace grouping, find by service/operation/tags, detail, stats, configure/singleton
- Propagator: W3C format, parse, roundtrip, tracestate, empty, OTLP bytes
- Bridge: agent→jaeger, parent linking, jaeger→agent, sync, write
- Instrumentation: middleware tracing, path exclusion, LLM decorator (success/error)
