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
