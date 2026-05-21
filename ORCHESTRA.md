# ORCHESTRA.md — Horizon Orchestra

Project conventions and coding standards.

## Project Overview

Horizon Orchestra is an agentic AI harness built on Kimi K2.5 as the core backbone model. It provides multi-model routing, parallel sub-agent swarms, persistent memory, and external service integrations — designed as the orchestration layer for the Horizon Monarch AI operating system.

## Architecture

```
horizon-orchestra/
├── horizon.py                  # Original CLI (sync, stdlib-only)
├── orchestra/
│   ├── __init__.py             # Package exports
│   ├── router.py               # Multi-model registry + intelligent routing
│   ├── agent_loop.py           # Async tool-calling loop (300 iterations)
│   ├── swarm.py                # DAG-based parallel sub-agent execution
│   ├── perplexity.py           # Sonar search + Agent API
│   ├── memory.py               # Persistent memory (SQLite + embeddings)
│   ├── vllm.py                 # Self-hosted inference management
│   ├── arch_a.py               # Architecture A: Monolithic orchestrator
│   ├── arch_c.py               # Architecture C: Native swarm
│   ├── arch_e.py               # Architecture E: Full production stack
│   ├── cli.py                  # Unified CLI for all architectures
│   ├── tools/                  # Tool implementations
│   │   ├── browser.py          # Playwright automation
│   │   └── ...
│   ├── connectors/             # External service integrations
│   │   ├── base.py             # Connector ABC + registry
│   │   ├── gmail.py            # Gmail (OAuth2)
│   │   ├── github.py           # GitHub (REST API)
│   │   ├── slack.py            # Slack (Web API)
│   │   ├── notion.py           # Notion (REST API)
│   │   ├── linear.py           # Linear (GraphQL)
│   │   ├── snowflake.py        # Snowflake (SQL)
│   │   ├── gcal.py             # Google Calendar
│   │   ├── gdrive.py           # Google Drive
│   │   ├── jira.py             # Jira (REST API v3)
│   │   ├── hubspot.py          # HubSpot CRM
│   │   ├── airtable.py         # Airtable
│   │   ├── stripe.py           # Stripe
│   │   ├── aws.py              # AWS (S3, Lambda, EC2, CloudWatch)
│   │   ├── mcp_bridge.py       # Model Context Protocol bridge
│   │   └── ...
│   └── skills/                 # Data science + domain skills
│       └── ...
├── tests/
│   ├── test_horizon.py         # Original CLI tests
│   ├── test_orchestra.py       # Core module tests
│   └── test_architectures.py   # Architecture A/C/E tests
├── scripts/                    # Deployment scripts (vLLM, SGLang)
├── requirements.txt
└── ORCHESTRA.md                # This file
```

## Code Standards

### Python
- **Version**: Python 3.11+ required. Use modern typing (`list[str]`, `dict[str, Any]`, `X | None`).
- **Async**: All model calls and I/O use `async/await` with `asyncio`. The `openai` SDK's `AsyncOpenAI` is the universal client.
- **Imports**: `from __future__ import annotations` in every file. Group: stdlib → third-party → local.
- **Type hints**: Required on all public functions and methods. Use `Any` sparingly.
- **Docstrings**: Required on all modules, classes, and public methods. Use Google-style or reStructuredText.
- **Logging**: Use `logging.getLogger("orchestra.<module>")`. Never `print()` in library code.
- **Error handling**: Catch specific exceptions. Return error dicts from tool handlers, never raise through the agent loop.

### Naming
- Files: `snake_case.py`
- Classes: `PascalCase`
- Functions/methods: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private: prefix with `_`

### Module Pattern
Every module must have:
1. Module docstring with usage example
2. `__all__` export list
3. Logger: `log = logging.getLogger("orchestra.<name>")`
4. Type hints on all public APIs

### Connector Pattern
All connectors follow this contract:
```python
class MyConnector(Connector):
    name = "my_service"
    description = "What it does."

    async def connect(self, credentials: dict[str, str]) -> bool: ...
    async def disconnect(self) -> None: ...
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]: ...
    def get_tool_definitions(self) -> list[dict[str, Any]]: ...
    @property
    def connected(self) -> bool: ...
```

- Auth via env vars first, then credentials dict fallback
- Return `{"error": "..."}` on failure, never raise
- Tool definitions use OpenAI function-calling format
- Tool names prefixed with service name: `gmail_search`, `github_create_issue`

### Skill Pattern
Skills are composable data science / domain capabilities:
```python
class MySkill:
    name = "skill_name"
    description = "What it does."

    async def execute(self, params: dict[str, Any]) -> dict[str, Any]: ...
    def get_tool_definitions(self) -> list[dict[str, Any]]: ...
```

- Skills generate code that runs in the sandbox
- They return structured results (dicts with data, metadata, viz paths)
- Skills can use connectors via the shared tool registry

## Dependencies

### Core (required)
- `openai>=1.60.0` — universal client for all model APIs
- `httpx>=0.27.0` — async HTTP for connectors

### Optional (per feature)
- `playwright` — browser automation
- `google-auth`, `google-auth-oauthlib`, `google-api-python-client` — Google services
- `snowflake-connector-python` — Snowflake
- `boto3` — AWS
- `fastapi`, `uvicorn` — Architecture E server
- `pandas`, `numpy`, `scipy`, `scikit-learn`, `matplotlib`, `seaborn`, `plotly` — data science skills

## Testing

- Framework: `unittest` with `unittest.mock`
- All tests must run offline (mock all API calls)
- Test files: `tests/test_<module>.py`
- Run: `python -m unittest discover tests -v`
- Every new module needs corresponding tests

## Key Design Decisions

1. **Kimi K2.5 as default backbone** — 10x cheaper than Claude, 200-300 stable tool calls, open weights for self-hosting.
2. **OpenAI-compatible everywhere** — Every model (Moonshot, OpenRouter, Together, Perplexity, vLLM, Ollama) uses the same `AsyncOpenAI` interface.
3. **Architecture layers** — A (single loop) → C (native swarm) → E (production stack). Each builds on the previous.
4. **Memory across architectures** — SQLite + embeddings, shared by all architectures via the same DB file.
5. **Connector-as-tool** — Connectors auto-register their tools into the agent's tool surface when connected.
6. **Skills-as-code-gen** — Data science skills generate and execute Python code in the sandbox, returning structured results.

## Git Workflow

- Branch: `master`
- Commit style: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`
- Test before push: `python -m unittest discover tests -v`

---

# Production Architecture Reference

> Last updated: 2026-05-21

## Environment Variables

All configuration lives in `.env` (copy from `.env.example`). The settings module (`orchestra/code_agent/settings.py`) validates at import time — missing required vars exit with a clear error message.

| Variable | Required in prod | Default (dev) | Description |
|----------|-----------------|---------------|-------------|
| `ORCHESTRA_ENV` | yes | `development` | Set to `production` to enable strict validation |
| `JWT_SECRET` | yes | auto-generated (volatile) | 64-char hex secret for token signing |
| `API_KEY_ENCRYPTION_KEY` | yes | auto-generated (volatile) | 32-char hex key for encrypting stored API keys |
| `CORS_ORIGINS` | yes | `*` (dev only) | Comma-separated allowed origins |
| `ORCHESTRA_HOST` | no | `127.0.0.1` | Bind address |
| `ORCHESTRA_PORT` | no | `8000` | Bind port |
| `ORCHESTRA_DB` | no | `orchestra.db` | Main SQLite database path |
| `ORCHESTRA_BILLING_DB` | no | `orchestra_billing.db` | Billing/user database path |
| `ORCHESTRA_LOGS_DB` | no | `~/.orchestra_logs.db` | Observability logs database |
| `REDIS_URL` | no | (none) | Redis for distributed rate-limiting; falls back to in-memory |
| `STRIPE_SECRET_KEY` | recommended | (none) | Stripe billing |
| `STRIPE_WEBHOOK_SECRET` | recommended | (none) | Stripe webhook verification |
| `SENTRY_DSN` | recommended | (none) | Sentry error tracking |
| `RATE_LIMIT_ENABLED` | no | `true` | Set `false` to disable rate limiting (tests) |
| `RATE_LIMIT_PER_MINUTE` | no | `120` | Default per-IP request limit |
| `RATE_LIMIT_CHAT_PER_MINUTE` | no | `20` | LLM chat endpoint limit |

Generate production secrets:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Middleware Stack Order

FastAPI middleware wraps ASGI in reverse registration order. The order below shows request processing sequence (first to last):

```
1. CORSMiddleware          — CORS headers, preflight responses
2. RateLimitMiddleware     — Per-IP token bucket, 429 on exceed
3. CSRFMiddleware          — Double-submit cookie protection
4. ObservabilityMiddleware — HTTP 4xx/5xx logging, slow request alerts
5. SecurityMiddleware      — Agent identity, capability auth, PII redaction, audit
6. AgentHeadersMiddleware  — Agent-aware response headers
   ─────────────────────────────────────────────────────
   FastAPI routes
```

All middleware degrades gracefully — if a middleware import fails, it logs a WARNING and the server continues without it.

---

## Server-Side API Key Storage

API keys are **never stored in localStorage**. Flow:
1. User pastes key in Settings → `PUT /api/keys/{provider}` 
2. Key is XOR-encrypted with `API_KEY_ENCRYPTION_KEY` + HMAC-SHA256 MAC
3. Ciphertext stored in `api_keys` table in SQLite
4. LLM routes resolve keys via `GET /api/keys/{provider}/resolve` (localhost-only)
5. Fallback: env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.)

Supported providers: `openai`, `anthropic`, `gemini`, `groq`, `mistral`, `cohere`, `together`, `fireworks`, `perplexity`, `stripe`, `sendgrid`, `twilio`, `github`, `openrouter`

---

## Database Migrations

Migrations live in `orchestra/code_agent/db/migrations.py`. They run automatically at server startup (idempotent). Check status via `GET /api/admin/migrations`.

**To add a migration:**
```python
def m_YYYYMMDD_NNN_description(conn: sqlite3.Connection) -> None:
    conn.execute("ALTER TABLE users ADD COLUMN ...")

_MIGRATIONS.append(Migration(
    version=9,
    name="description",
    up="ALTER TABLE ...",
    down="SELECT 1",  # or DROP/revert SQL
))
```

**Rules:**
- Never delete or reorder migrations
- Use `IF NOT EXISTS` / `IF EXISTS` guards in SQL
- `down` must be a valid SQL string (can be `"SELECT 1"` if irreversible)

---

## Rate Limiting

- **Default**: 120 req/min per IP (in-memory token bucket)
- **`/api/chat`**: 20 req/min per IP
- **`/v1/auth/login`**: 10 req/min per IP
- **`/v1/auth/register`**: 5 req/min per IP
- **`/api/keys`**: 30 req/min per IP

Redis is used when `REDIS_URL` is set; falls back to in-memory automatically.

Response on exceed:
```json
{ "detail": "Too many requests", "retry_after_seconds": 4.2 }
```

---

## TTL Cache (Market Data)

Market data is cached in-process using `orchestra/code_agent/cache/ttl.py`:

| Cache | TTL | Use |
|-------|-----|-----|
| `price_cache` | 60s | Quote prices, movers |
| `news_cache` | 5 min | News headlines |
| `search_cache` | 10 min | Ticker search results |
| `_hist_cache` | 5 min | Historical OHLCV |

---

## Testing

```bash
# All tests
pytest tests/ -v

# Integration tests only (requires server stack)
pytest tests/test_integration_core.py -v

# Unit tests (offline)
python -m unittest discover tests -v
```

Integration tests in `tests/test_integration_core.py` spin up the full `create_ui_app()` factory using FastAPI TestClient. They test:
- Auth: register, login, JWT
- Sessions: CRUD
- Logs API: ingest, list, stats, clear
- API Keys: store, check, delete, provider validation
- Finance API: health, accounts, transactions
- Migration status endpoint
- Settings validation

---

## Production Readiness Checklist

| Item | Status |
|------|--------|
| Settings validation at startup | ✅ `settings.py` fails fast |
| CORS locked to known origins | ✅ `CORS_ORIGINS` env var |
| API keys server-side encrypted | ✅ XOR+HMAC in SQLite |
| Rate limiting (no Redis required) | ✅ In-memory token bucket |
| Market data TTL cache | ✅ 60s–10min by data type |
| Database migrations | ✅ Append-only, idempotent |
| Silent `except: pass` removed | ✅ All critical paths log WARNINGs |
| Integration tests | ✅ `tests/test_integration_core.py` |
| Observability (logs, metrics) | ✅ SQLite log store + UI panel |
| CSRF protection | ✅ Double-submit cookie |
| JWT auth + refresh tokens | ✅ RS256/HS256 + rotation |
| Stripe billing | ✅ Routes + webhook |
| Health endpoint | ✅ `/api/health` |
| Prometheus metrics | ✅ `/metrics` |
| Docker + Compose | ✅ `Dockerfile`, `docker-compose.yml` |
| Secrets in `.env` not code | ✅ Via settings.py |
| WAL mode on SQLite | ✅ Enabled via migration 8 |

**Current production readiness score: ~68/100**

Remaining gaps to reach 90+:
1. PostgreSQL option (for multi-instance deployments) — add `DATABASE_URL` support to `MigrationEngine`
2. Email verification flow
3. Real browser E2E tests (Playwright)
4. Load testing results
5. Security audit / penetration test results
6. Backup / restore procedure for SQLite files
