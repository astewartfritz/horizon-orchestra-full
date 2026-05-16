# CI/CD Pipeline — Orchestra

## Pipeline Overview

```
Feature Branch → PR → Build → Test → Lint → Quality Gate → Container → Staging → Production
                        └─── parallel ───┘                    (ArgoCD)
```

## Supported Platforms

| Platform | File | Trigger |
|----------|------|---------|
| Jenkins | `Jenkinsfile` | PR + push to main |
| GitLab CI | `.gitlab-ci.yml` | PR + push to main |
| ArgoCD | `argocd/application.yaml` | Sync from container registry |

## Pipeline Stages

| Stage | What it does | Approx time |
|-------|-------------|-------------|
| `build` | Install deps, compile, Docker build | 2-5 min |
| `test` | Run all tests with coverage | 3-8 min |
| `lint` | Ruff + mypy + bandit (Python), ESLint (TS) | 1-2 min |
| `quality` | Coverage gate (≥80%), security scan, license check | 2-3 min |
| `docker` | Multi-stage build, tag, push to registry | 3-5 min |
| `deploy` | ArgoCD sync or Helm upgrade | 1-2 min |

## Quick Start

```bash
# Local CI simulation
make build
make test
make lint

# Full pipeline locally
make ci

# Deploy with ArgoCD
make deploy ARGOCD_SERVER=my-argocd.example.com
```

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DOCKER_REGISTRY` | Yes | — | Container registry URL |
| `DOCKER_TAG` | No | `git sha` | Image tag |
| `PYTHONPATH` | No | `src;src\code_agent` | Python module path |
| `ARGOCD_SERVER` | No | — | ArgoCD API server |
| `COVERAGE_THRESHOLD` | No | `80` | Min coverage percentage |
