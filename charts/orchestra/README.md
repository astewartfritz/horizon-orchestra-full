# Orchestra Helm Chart

Deploy Orchestra on Kubernetes with horizontal scaling, Ollama sidecar, and full observability.

## Quick start

```bash
# Add values and install
helm install orchestra ./charts/orchestra --values my-values.yaml

# Or with inline overrides
helm install orchestra ./charts/orchestra \
  --set provider=ollama \
  --set model=nemotron-mini \
  --set autoscaling.enabled=true \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=orchestra.example.com
```

## Architecture

```
┌─────────────────────────────────────────────────────┐
│  Kubernetes Cluster                                  │
│                                                      │
│  ┌─────────────────────┐  ┌──────────────────────┐  │
│  │ Orchestra Deployment │  │ Ollama Deployment    │  │
│  │ (scales 2-10)        │  │ (1 replica)          │  │
│  │ port 8000            │  │ port 11434           │  │
│  └─────────┬───────────┘  └──────────┬───────────┘  │
│            │                         │               │
│  ┌─────────▼─────────────────────────▼───────────┐  │
│  │  Service (ClusterIP)                          │  │
│  │  orchestra:8000  →  Orchestra Pod(s)         │  │
│  │  orchestra-ollama:11434 → Ollama Pod          │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │  Ingress (orchestra.example.com) → Service    │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │  HPA (CPU > 70% or Memory > 80%)             │  │
│  │  → scales Orchestra from 2 to 10 replicas     │  │
│  └───────────────────────────────────────────────┘  │
│                                                      │
│  ┌───────────────────────────────────────────────┐  │
│  │  PVCs: 10Gi (workspace) + 50Gi (Ollama models)│  │
│  └───────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

## Configuration

| Parameter | Default | Description |
|-----------|---------|-------------|
| `replicaCount` | `2` | Orchestra pod replicas |
| `provider` | `ollama` | LLM provider (ollama, openai, anthropic) |
| `model` | `nemotron-mini` | Model to use |
| `ollama.enabled` | `true` | Deploy Ollama sidecar |
| `ollama.resources.limits.memory` | `16Gi` | Ollama memory limit (model-dependent) |
| `autoscaling.enabled` | `true` | Enable HPA |
| `autoscaling.minReplicas` | `2` | Minimum pods |
| `autoscaling.maxReplicas` | `10` | Maximum pods |
| `ingress.enabled` | `false` | Enable ingress |
| `persistence.size` | `10Gi` | Workspace PVC size |
| `ollama.persistentVolume.size` | `50Gi` | Model storage PVC size |

## Scaling

- **CPU threshold**: 70% → scale up
- **Memory threshold**: 80% → scale up
- **Scale-down**: 5-minute stabilization window, 50% pod reduction per minute
- **Scale-up**: Immediate, 100% increase per 15 seconds

## Storage

- Orchestra workspace: 10Gi PVC (skills, sessions, artifacts)
- Ollama models: 50Gi PVC (model weights, can be large for 7B+ models)

## Observability

Prometheus metrics on port 8000 at `/api/metrics`. OTel export configurable via `extraEnv.OTEL_EXPORTER_OTLP_ENDPOINT`.

## Deployment with custom values

```yaml
# my-values.yaml
provider: openai
model: gpt-4o
ollama:
  enabled: false
replicaCount: 3
autoscaling:
  minReplicas: 3
  maxReplicas: 20
extraEnv:
  OTEL_ENABLED: "true"
  OTEL_EXPORTER_OTLP_ENDPOINT: "http://grafana-alloy.monitoring:4317"
  LANGFUSE_HOST: "https://cloud.langfuse.com"
  LANGFUSE_PUBLIC_KEY: "pk-..."
  LANGFUSE_SECRET_KEY: "sk-..."
```
