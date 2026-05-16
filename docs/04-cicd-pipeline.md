# CI/CD Pipeline — Jenkins + GitLab + ArgoCD

> **Module:** `ci-cd/` — 34 tests

Orchestra provides production-ready CI/CD configurations for three major platforms: Jenkins (declarative pipeline), GitLab CI (multi-stage YAML), and ArgoCD (GitOps deployment with Kustomize).

---

## Pipeline Overview

```
Feature Branch → PR → Build → Test → Lint → Quality → Docker → Staging → Production
                              (parallel)            (gate)            (manual)
```

---

## Jenkins — `ci-cd/Jenkinsfile`

Declarative pipeline with Kubernetes pod agent.

**Stages:**
| Stage | Parallel | Description |
|-------|----------|-------------|
| Build | Yes | Python deps (`pip install -e ".[dev]"`) + Node deps (`npm ci`) |
| Test | Yes | Python (pytest + jUnit + coverage), Node (npm test), API (Express) |
| Lint & Quality | Yes | Ruff + mypy, Bandit security, coverage gate (≥80%), license check |
| Docker | No | Multi-stage build, tag with commit SHA, push to registry (main only) |
| Deploy Staging | No | Auto on main branch |
| Deploy Production | No | Manual approval gate |

**Pod template:** Python 3.13 + Docker 27 + Node 22, shared Docker socket

---

## GitLab CI — `ci-cd/.gitlab-ci.yml`

Multi-stage pipeline with GitLab-native features.

**Key features:**
- **Caching:** pip + npm across stages
- **Artifacts:** jUnit reports, coverage.xml, SAST (Bandit), license reports
- **Environments:** staging (`staging.orchestra.ai`), production (`orchestra.ai`)
- **Rules:** main branch → auto staging, tags (`v*`) → auto docker, production → manual
- **Docker-in-Docker:** Secure TLS-based DinD for container builds

**Jobs:**
```
build: python-deps, node-deps
test: python-tests, node-tests
lint: python-lint, typescript-lint
quality: coverage-gate, security-scan
docker: docker-build (rules: main + tags)
deploy: deploy-staging (auto), deploy-production (manual)
```

---

## ArgoCD — `ci-cd/argocd/`

GitOps deployment with 3 Application resources and Kustomize overlays.

### Applications

| Name | Source | Namespace | Auto-sync |
|------|--------|-----------|-----------|
| `orchestra` | `charts/orchestra/` (Helm) | `orchestra` | prune + selfHeal |
| `orchestra-staging` | Kustomize overlay | `orchestra-staging` | prune + selfHeal |
| `orchestra-production` | Kustomize overlay | `orchestra-production` | prune + selfHeal |

### AppProject RBAC

```yaml
roles:
  - name: ci-deployer
    policies:
      - p, proj:orchestra:ci-deployer, applications, sync, orchestra-staging/*, allow
      - p, proj:orchestra:ci-deployer, applications, sync, orchestra-production/*, allow
```

### Kustomize Resources
| Resource | Purpose |
|----------|---------|
| `deployment.yaml` | Rolling update, 2 replicas, resource limits, 3 probes |
| `service.yaml` | ClusterIP, ports 8000 + 8001 |
| `ingress.yaml` | TLS via cert-manager, nginx ingress |
| `configmap.yaml` | OTel, LangChain, CORS, log level config |
| `hpa.yaml` | 2-10 pods, CPU 70% / memory 80% |

---

## Docker — `ci-cd/Dockerfile`

Multi-stage build:
```
Stage 1: Python builder  (python:3.13-slim → pip install + build wheel)
Stage 2: Node builder    (node:22-alpine → npm ci)
Stage 3: Production      (python:3.13-slim → install wheel + copy TS)
```

Healthcheck: `curl -f http://localhost:${PORT}/health`

---

## Local Development — `ci-cd/Makefile`

```bash
make build       # Install all dependencies
make test        # Run all tests with coverage
make lint        # Run linters (ruff, mypy, bandit)
make quality     # Coverage gate + license check
make docker      # Build Docker image
make ci          # Full pipeline (build → test → lint → quality → docker)
make deploy      # Deploy (set ENV=staging|production, TAG=...)
```

## Deploy Script — `ci-cd/scripts/deploy.py`

```bash
python ci-cd/scripts/deploy.py --env staging --tag abc1234
python ci-cd/scripts/deploy.py --env production --tag abc1234 --method helm
```

Supports ArgoCD sync (primary) and Helm upgrade (fallback). Reads `ARGOCD_SERVER`, `ARGOCD_TOKEN`, `DOCKER_REGISTRY` from environment.

## Test Coverage (34 tests)

- Dockerfile: exists, multi-stage, healthcheck, exposed port
- Dockerignore: key entries
- Makefile: all targets present
- Jenkinsfile: stages, parallel, post-actions, kubernetes agent
- GitLab CI: stages, cache, artifacts, environments
- ArgoCD: Application spec, AppProject, Kustomize resources
- Scripts: all 4 parse correctly, coverage XML parsing
- Helm values: required keys present
