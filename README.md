# Horizon Orchestra

Multi-model agentic AI orchestration platform — agent runtime, model router, security stack, P2P mesh, DAG workflows, enterprise connectors, and AI-for-science subsystem. Designed for production deployments in regulated environments.

## Quick Start

```bash
pip install -e ".[server]"
export OPENAI_API_KEY=sk-...
horizon run "summarise the latest kernel commits"
```

Or launch the web UI:

```bash
horizon serve
# Open http://localhost:8000
```

## CLI

| Command | Description |
|---|---|
| `horizon run <task>` | Execute a task (selectable architecture A/B/C/D/E) |
| `horizon serve` | Start API + web UI server |
| `horizon gui` | Serve the dashboard |
| `horizon status` | System status and module info |
| `horizon science <question>` | Literature-to-experiment pipeline |
| `horizon miles` | Personal AI assistant with multi-channel adapters |
| `horizon validate <schema> <file>` | Validate JSON against schema |
| `horizon --version` | Show version |

## Architecture

Orchestra operates across six segments:

1. **Core Agent** — Pluggable agent loop (monolithic, RAG, swarm, MCP hub, production orchestrator) with multi-model router (OpenAI, Anthropic, Google, Mistral, Groq, Kimi, Gemma, Opus)
2. **Security** — 5-layer defense-in-depth (PermissionGate, InputSanitizer, OutputMonitor, RateLimiter, CircuitBreaker) + HMAC-chained audit ledger + field-level AES-256-GCM encryption
3. **Enterprise Connectors** — Salesforce, Google Workspace, Microsoft 365, Meta Business, Amazon Business, Slack, GitHub, Jira, Notion, HubSpot, Stripe, Snowflake, and 15+ more
4. **P2P Agent Mesh** — Decentralized agent registry, node networking, and routing for distributed agent coordination
5. **DAG Workflow Engine** — Observable, multi-step agent pipelines with human handoff, rollback, and SLA monitoring
6. **AI-for-Science** — PubChem/RDKit ingestion, cheminformatics/bioinformatics analysis, molecular docking workflows, lab report generation

## Key Features

- **5 agent architectures**: Monolithic (A), RAG Pipeline (B), Swarm (C), MCP Tool Hub (D), Production Orchestrator (E)
- **Multi-model routing**: Automatic model selection by cost, latency, capability, or tool constraint with fallback
- **P2P agent mesh**: Distributed registry, gossip protocol, NAT traversal, and encrypted inter-agent communication
- **DAG workflows**: Conditional branching, parallel execution, human handoff steps, SLA enforcement, retry policies
- **Observability**: Three-layer (component, experience, decision) via AgentHarness + OpenTelemetry + Tempo/Jaeger/Grafana
- **Embedding & vector stores**: PGVector, Pinecone, Supabase, and in-memory with unified pipeline and LRU cache
- **Red-teaming**: 85+ attack vectors across 8 categories (Stanford STRIKE protocol) with Monte Carlo simulation
- **OS-level sandboxing**: Linux namespaces, seccomp-BPF, cgroup v2 for agent execution isolation
- **Domain compliance**: Healthcare (HIPAA), legal (GDPR), financial (SOX) — field encryption, break-glass, consent management, data lifecycle policies
- **Cross-session memory**: Timeline REST API with recall and summarization
- **Speech-to-text**: Browser SpeechRecognition web app + transcription API
- **Canary deployments**: Automated blue/green with CodeDeploy, staged traffic shifting, rollback on health failure
- **Database backup**: pg_dump to S3 with versioning, lifecycle transitions, and restore scripts

## API

| Method | Path | Description |
|---|---|---|
| POST | `/v1/auth/register` | Create account |
| POST | `/v1/auth/login` | Login |
| POST | `/v1/run` | Execute task |
| WS | `/v1/stream` | WebSocket streaming |
| POST | `/v1/query` | Direct model query |
| POST | `/v1/memory/search` | Semantic memory search |
| GET | `/v1/memory/list` | List memories |
| GET | `/v1/models` | List available models |
| POST | `/v1/billing/checkout` | Stripe checkout |
| POST | `/api/science/*` | Science subsystem |
| GET | `/api/health` | Health check |

Full API at `/docs` when server is running (OpenAPI/Swagger).

## Integrations

**LLM Providers**: OpenAI, Anthropic, Google Gemini, Mistral, Groq, Kimi K2.5, Gemma 4, Opus 4, Perplexity Sonar, vLLM, Ollama

**Enterprise**: Salesforce, Google Workspace, Microsoft 365, Meta Business, Amazon Business, Slack, GitHub, GitLab, Jira, Linear, Notion, Airtable, Monday.com, HubSpot, Stripe, Snowflake, n8n, Zapier, AWS

**Channels**: Slack, Telegram, WhatsApp, Gmail, Instagram, iMessage

**Observability**: OpenTelemetry, Tempo, Jaeger, Grafana, Prometheus, LangFuse

**Vector Stores**: PGVector (PostgreSQL), Pinecone, Supabase, in-memory

**CI/CD**: GitHub Actions, Jenkins, GitLab CI, ArgoCD, Helm

## Deploy

```bash
# Docker
docker compose up -d

# Production (canary)
python scripts/canary_deploy.py --environment production

# Database backup
scripts/backup.sh
```

## Development

```bash
make test       # pytest
make lint       # ruff check
make typecheck  # mypy
make format     # ruff format

# Full test suite
python -m pytest tests/ -v --tb=short --cache-clear
```

## License

Proprietary — Copyright Ashton Fritz 2026. See [LICENSE](LICENSE).
