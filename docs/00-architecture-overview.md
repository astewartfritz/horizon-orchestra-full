# Orchestra — Architecture Overview

> **One platform. Six segments. Infinite scale.**
> Orchestra is a modular, AI-native platform for building autonomous software agents, financial systems, logistics operations, and enterprise-grade APIs — all served through a unified architecture.

---

## System Context

```
User / Developer
    │
    ▼
┌──────────────────────────────────────────────────────────────┐
│                    Orchestra Core (Agent Loop)                │
│  LLM → Plan → Execute Tools → Observe → Reflect → Repeat     │
└──────────────────────┬──────────────────────────────────────┘
                       │
     ┌─────────────────┼──────────────────┬──────────────────┐
     ▼                 ▼                  ▼                  ▼
┌──────────┐    ┌──────────┐       ┌──────────┐       ┌──────────┐
│ Finance  │    │ Logistics│       │ Gateway  │       │ Security │
│ Engine   │    │ v1 + v2  │       │ API + SD │       │ Layers   │
└──────────┘    └──────────┘       └──────────┘       └──────────┘
     │                │                  │                  │
     ▼                ▼                  ▼                  ▼
┌──────────────────────────────────────────────────────────────┐
│              Infrastructure (Observability + CI/CD)          │
│  OTel → Tempo → Jaeger │ Prometheus │ Jenkins/GitLab/ArgoCD  │
└──────────────────────────────────────────────────────────────┘
```

---

## Segment Map

| # | Segment | Module | Language | Purpose |
|---|---------|--------|----------|---------|
| 1 | **Core Agent** | `agent.py`, `cli.py` | Python | LLM-driven autonomous coding agent |
| 2 | **API Gateway** | `api_gateway/` | Python | Rate limiting, JWT/API-key auth, validation, tracing |
| 3 | **Service Discovery** | `service_discovery/` | Python | Registry, DNS resolver, LB strategies, health checks |
| 4 | **Tracing** | `tracing/` + `tracing/tempo/` | Python + YAML | OTel → Tempo → Jaeger → Grafana pipeline |
| 5 | **CI/CD** | `ci-cd/` | Groovy/YAML/Python | Jenkins, GitLab CI, ArgoCD, Kustomize, Docker |
| 6 | **Finance** | `finance/` | Python + TS | Formula engine, ledger, analytics, AI brain |
| 7 | **Logistics v1** | `logistics/` | Python | Fleet, routing, supply chain, AI brain |
| 8 | **Logistics v2** | `logistics2/` | Python + Go + TS | VRP/TSP, forecasting, pricing, dispatch, telemetry, workflows |
| 9 | **Multi-Channel** | `channels/ts/` | TypeScript | Slack, Telegram, WhatsApp, Discord, iMessage, Email |
| 10 | **Security** | `security/` | Python | 4-layer defense-in-depth, channel auth, egress control |
| 11 | **UI** | `ui/` | Python + HTML/CSS/JS | Dashboard, spreadsheet, brand sites (Create, Finance, Logistics) |
| 12 | **Observability** | `telemetry/` | Python | Prometheus metrics, OTel exporters, LangFuse |
| 13 | **K8s Deployment** | `charts/orchestra/` | YAML | Helm chart: HPA, Ollama sidecar, ingress, PDB |

---

## Data Flow

```
              ┌──────────────┐
              │   Web UI     │  ← HTML/CSS/JS served via FastAPI
              └──────┬───────┘
                     │ REST (JSON)
              ┌──────▼───────┐
              │   Gateway    │  ← Rate limiter → Auth → Validation → Tracing
              └──────┬───────┘
                     │
        ┌────────────┼────────────┬──────────────┐
        ▼            ▼            ▼              ▼
   ┌────────┐  ┌─────────┐  ┌─────────┐   ┌──────────┐
   │ Finance│  │Logistics│  │ Channels│   │   Agent  │
   │Engine  │  │Engine   │  │  (TS)   │   │  Engine  │
   └────────┘  └─────────┘  └─────────┘   └──────────┘
        │            │                            │
        ▼            ▼                            ▼
   ┌─────────────────────────────────────────────────┐
   │         Telemetry / Tracing / Metrics           │
   │  OTel Collector → Tempo → Jaeger → Grafana      │
   │  Prometheus → Metrics Dashboard                  │
   └─────────────────────────────────────────────────┘
```

---

## Quick Reference

| URL | Service | Port |
|-----|---------|------|
| `/` | Main Orchestra UI | 8000 |
| `/create` | Orchestra Create brand | 8000 |
| `/finance` | Orchestra Finance brand | 8000 |
| `/finance/app` | Finance dashboard + spreadsheet | 8000 |
| `/logistics` | Orchestra Logistics brand | 8000 |
| `/logistics/app` | Logistics dashboard | 8000 |
| `/api/finance/*` | Finance REST API | 8000 |
| `/api/logistics/*` | Logistics REST API | 8000 |
| `/api/gateway/*` | Gateway admin | 8000 |
| Channels bridge | Slack/Telegram/WhatsApp/Discord | 4500 |

---

## Test Coverage

| Segment | Tests | Status |
|---------|-------|--------|
| Core Agent | — | inherited |
| API Gateway | 31 | ✅ |
| Service Discovery | 50 | ✅ |
| Tracing | 40 | ✅ |
| CI/CD | 34 | ✅ |
| Finance | 65 | ✅ |
| Logistics v1 | 49 | ✅ |
| Logistics v2 | 42 | ✅ |
| **Total** | **311+** | **✅** |

---

## Language Distribution

```
Python:    ~12,000 lines  (agent core, engines, gateway, CI/CD, tests)
TypeScript: ~1,500 lines  (channel adapters, finance orchestrator)
HTML/CSS/JS:~5,000 lines  (UI dashboards, brand pages)
YAML:       ~1,500 lines  (Helm chart, CI/CD configs, Docker Compose)
Go:           ~200 lines  (telemetry scaffold)
```

---

*For detailed documentation on each segment, see the corresponding file in `docs/`.*
