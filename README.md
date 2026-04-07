# Horizon Orchestra

A multi-model agentic AI harness for Python — run, route, and coordinate across 25 models with a single unified interface.

---

## What It Is

Horizon Orchestra is a production-ready orchestration framework for building autonomous AI agents in Python. v0.3.0 ships with:

- **23 modules** covering routing, agent loops, swarm coordination, memory, security, speech, browser automation, billing, skills, and more
- **356+ tests** across unit, integration, and end-to-end suites
- **28,000+ lines** of documented, typed Python
- **25 registered models** spanning Gemma 4, Claude Opus 4.6, Kimi K2.5, GPT-4o, Sonar, Grok, and more
- **9 connectors** for external services (Perplexity, ElevenLabs, Deepgram, Stripe, Playwright, and others)
- Three pluggable **architectures** (Monolithic, Swarm, Production/FastAPI)

Whether you're building a single-agent code assistant or a multi-agent research pipeline with billing, memory, and speech — Orchestra provides the wiring.

---

## Quick Start

```bash
pip install horizon-orchestra
# or with all optional extras:
pip install "horizon-orchestra[all]"
```

### Architecture A — Monolithic Agent

```python
from orchestra import MonolithicAgent, MonolithicConfig

config = MonolithicConfig(model="kimi-k2.5")
agent = MonolithicAgent(config=config)

async for event in agent.stream("Build a REST API for task management"):
    print(event)
```

### Architecture C — Swarm Agent

```python
from orchestra import SwarmAgent, SwarmConfig

config = SwarmConfig(coordinator_model="claude-opus-4.6-openrouter")
agent = SwarmAgent(config=config)

async for event in agent.stream("Research competitors and write a report"):
    print(event)
```

### Low-level Agent Loop

```python
from orchestra import ModelRouter, AgentLoop, create_default_tools, AgentConfig

router = ModelRouter()
tools  = create_default_tools(router)
config = AgentConfig(model="claude-opus-4.6-openrouter")
agent  = AgentLoop(router, tools, config)

async for event in agent.run("Summarise the top 5 AI papers this week"):
    print(event)
```

---

## Model Support

| Model | Provider | Context | Input $/1M | Output $/1M | Thinking | Vision |
|---|---|---|---|---|---|---|
| gemma-4-31b | Google AI / OpenRouter | 128K | $0.30 | $0.90 | — | Yes |
| gemma-4-26b-moe | Google AI / OpenRouter | 128K | $0.20 | $0.60 | — | Yes |
| gemma-4-e4b | Ollama (local) | 128K | free | free | — | Yes |
| claude-opus-4.6 | Anthropic | 200K | $15.00 | $75.00 | Yes | Yes |
| claude-opus-4.6-openrouter | OpenRouter | 200K | $15.00 | $75.00 | Yes | Yes |
| kimi-k2.5 | Moonshot / OpenRouter | 128K | $0.60 | $2.50 | — | — |
| gpt-4o | OpenAI | 128K | $2.50 | $10.00 | — | Yes |
| gpt-4o-mini | OpenAI | 128K | $0.15 | $0.60 | — | Yes |
| sonar | Perplexity | 127K | $1.00 | $1.00 | — | — |
| sonar-pro | Perplexity | 127K | $3.00 | $15.00 | — | — |
| sonar-reasoning | Perplexity | 127K | $1.00 | $5.00 | Yes | — |
| grok-3 | xAI | 131K | $3.00 | $15.00 | — | — |
| grok-3-mini | xAI | 131K | $0.30 | $0.50 | Yes | — |

Run `orchestra models list` to see the full table with live availability.

---

## Architectures

### Architecture A — Monolithic (`arch_a.py`)

A single `MonolithicAgent` that executes the full task in one agent loop. Best for focused, single-domain tasks. The agent has access to all registered tools, persistent memory, optional security middleware, and usage tracking. Configurable via `MonolithicConfig` with sensible defaults: Kimi K2.5 as the backbone model, 300-iteration ceiling, and automatic skill activation.

### Architecture C — Swarm (`arch_c.py`)

A `SwarmAgent` that decomposes work into parallel sub-tasks, each executed by a specialised worker agent. The coordinator model (configurable) plans the decomposition, dispatches workers concurrently, and synthesises results. Workers share a common tool registry but maintain independent conversation histories. Best for research, multi-step pipelines, and tasks that benefit from parallel exploration.

### Architecture E — Production (`arch_e.py`)

A `ProductionOrchestrator` backed by a FastAPI application server. Exposes REST endpoints for task submission, streaming events, health checks, metrics, and connector management. Start it with `orchestra serve` or deploy via the generated `docker-compose.yml`. Architecture E wraps Architecture A or C as its execution backend, adding authentication middleware, rate limiting, structured logging, and Stripe billing hooks.

---

## Skills

Skills are markdown files (`SKILL.md` format) with a YAML frontmatter header describing the skill's name, version, trigger keywords, required tools, preferred models, and chaining targets. The body is the full instruction text injected into the agent's system prompt when the skill activates.

### Built-in Skills

| Skill | Trigger Domain | Chains To |
|---|---|---|
| `web-research` | research, search, news | `report-writing` |
| `code-generation` | code, build, implement | `code-review` |
| `code-review` | review, audit, refactor | — |
| `report-writing` | report, summarise, write | — |
| `data-analysis` | data, analyse, statistics | `report-writing` |
| `browser-automation` | browser, scrape, form | — |
| `api-integration` | API, integration, webhook | `code-generation` |
| `memory-management` | remember, recall, forget | — |

### Auto-Activation

`SkillActivator` scores incoming tasks against all registered skills and injects the top-matching skills into the system prompt automatically. No manual configuration needed.

### Skill Chaining

Skills declare `chains_to` targets. After completing a research skill, Orchestra can automatically activate `report-writing` to convert raw findings into a polished deliverable.

### Custom Skills

```bash
orchestra skills create my-skill "Analyses financial statements" \
    --instructions path/to/instructions.md
```

---

## Model Council

Model Council runs the same prompt through multiple models in parallel and synthesises the responses.

```python
from orchestra import ModelCouncil, ModelRouter

council = ModelCouncil(router=ModelRouter())
result = await council.deliberate(
    prompt="What is the best database for a real-time chat app?",
    models=["kimi-k2.5", "claude-opus-4.6-openrouter", "gpt-4o"],
    orchestrator="claude-opus-4.6-openrouter",
)
print(result.to_markdown())
print(f"Agreement score: {result.agreement_score:.2f}")
```

Each `ModelVote` captures the individual model's response, reasoning, and confidence. The orchestrator model synthesises all votes into a final `CouncilResult` with an agreement score (0–1) and a list of models that failed or timed out. Use from the CLI with `orchestra council`.

---

## Speech & Audio

Orchestra provides a unified `SpeechProvider` with pluggable backends.

### Speech-to-Text Backends

| Backend | Model | Notes |
|---|---|---|
| `whisper_local` | faster-whisper (local) | CPU/GPU, offline |
| `whisper_api` | OpenAI Whisper | Cloud API |
| `deepgram` | Nova-3 | Streaming, low latency |
| `assemblyai` | AssemblyAI Universal-2 | Async, speaker diarisation |
| `google` | Google Speech-to-Text v2 | GCP |
| `azure` | Azure Cognitive Services | Microsoft |

### Text-to-Speech Backends

| Backend | Model | Notes |
|---|---|---|
| `elevenlabs` | Multilingual v3 | Voice cloning, 29 languages |
| `openai_tts` | TTS-1 / TTS-1-HD | 6 built-in voices |
| `google_tts` | Chirp HD | GCP |
| `azure_tts` | Neural TTS | Microsoft |
| `deepgram_tts` | Aura-2 | Streaming-first |
| `pyttsx3` | System TTS | Offline fallback |

Install speech extras: `pip install "horizon-orchestra[speech]"`.

---

## Security

`SecurityMiddleware` wraps every tool call with a configurable 5-layer pipeline:

1. **Input Sanitizer** — strips prompt injections and dangerous patterns from tool arguments
2. **Permission Gate** — enforces allowlists/denylists on tool names and argument values
3. **Rate Limiter** — token-bucket rate limiting per user, per tool, and globally
4. **Output Monitor** — scans tool results for PII, secrets, and harmful content
5. **Audit Logger** — writes signed, tamper-evident logs of every security decision

### Preset Policies

| Policy | Use Case |
|---|---|
| `strict_policy` | Air-gapped or safety-critical deployments |
| `standard_policy` | General production workloads |
| `permissive_policy` | Internal developer tooling |
| `safety_critical_policy` | Medical, legal, financial agents |

---

## Browser Automation

`BrowserConnector` wraps Playwright Chromium with three connection modes:

- **Local** — launches a headless Chromium process in the current environment
- **Remote CDP** — connects to an existing Chrome DevTools Protocol endpoint (e.g., a cloud browser service)
- **Persistent** — reuses a browser profile across sessions (useful for authenticated workflows)

Supported actions: `navigate`, `click`, `type`, `fill`, `select`, `get_content`, `get_text`, `screenshot`, `evaluate`, `extract`, `extract_table`, `scroll`, `hover`, `press_key`, `get_state`, `new_tab`, `get_cookies`, `set_cookies`, `wait_for`, `upload_file`.

Install: `pip install "horizon-orchestra[playwright]" && playwright install chromium`

---

## Billing

`BillingManager` integrates with Stripe to meter LLM token usage and tool calls. Four pre-configured tiers:

| Tier | Price | Monthly LLM Tokens | Tool Calls |
|---|---|---|---|
| Free | $0/mo | 100,000 | 500 |
| Starter | $29/mo | 1,000,000 | 10,000 |
| Pro | $99/mo | 5,000,000 | 50,000 |
| Enterprise | $499/mo | Unlimited | Unlimited |

`UsageTracker` enforces budget ceilings in real time — once a tier limit is reached, further tool calls are blocked gracefully without crashing the agent loop. `NullBillingManager` and `NullUsageTracker` are drop-in no-ops for development.

Install: `pip install "horizon-orchestra[stripe]"`

---

## CLI

```
orchestra --help

usage: horizon-orchestra [-h] [-v] {run,serve,docker,memory,gemma4,skills,tasks,council,models,connectors} ...

subcommands:
  run           Run a task (Architecture A or C)
    --arch      A (monolithic) | C (swarm)
    --model     Model name  [default: kimi-k2.5]

  serve         Start Architecture E server
    --port      Port  [default: 3000]
    --model     Backend model

  docker        Generate Docker Compose files

  memory        Memory operations
    search      Search memories
    store       Store a memory
    list        List all memories

  gemma4        Gemma 4 model utilities
    info        Show model card
    modelfile   Generate Ollama Modelfile
    vllm        Generate vLLM serve command

  skills        Skill management
    list        List all available skills
    match       Find skills matching a task description
    show        Show a skill's full instructions
    create      Create a skill from a description

  tasks         Task management
    list        List tasks (filter by status)
    submit      Submit a task (with optional cron schedule)
    status      Get task status
    pause       Pause a running task
    resume      Resume a paused task
    cancel      Cancel a task

  council       Model Council — parallel multi-model deliberation
    --models    Comma-separated model names
    --orchestrator  Model to synthesise results

  models        List and query available models
    list        List all registered models
    info        Get model capabilities

  connectors    List available connectors
    --status    Show connection status
```

---

## Docker

Generate and start a full production stack in two commands:

```bash
orchestra docker --output ./deploy
cd deploy
cp .env.example .env   # fill in API keys
docker compose up -d
```

The generated `docker-compose.yml` includes the Orchestra API server, a Redis instance for task queuing, and a Postgres database for persistent memory and usage records. A Caddy reverse proxy with automatic TLS is included for production domains.

---

## Connectors

Orchestra ships with 9 built-in connectors:

| Connector | Service | Auth |
|---|---|---|
| `perplexity` | Perplexity Sonar search | API key |
| `openrouter` | 200+ models via OpenRouter | API key |
| `anthropic` | Claude models direct | API key |
| `elevenlabs` | ElevenLabs TTS | API key |
| `deepgram` | Deepgram STT | API key |
| `stripe` | Stripe billing & metering | Secret key |
| `playwright` | Chromium browser automation | None |
| `google_ai` | Gemma 4 via Google AI | API key |
| `xai` | Grok models | API key |

List connectors and their live connection status:

```bash
orchestra connectors --status
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | Recommended | OpenRouter — access to 200+ models |
| `ANTHROPIC_API_KEY` | Optional | Claude models direct |
| `PERPLEXITY_API_KEY` | Optional | Web search via Sonar |
| `GOOGLE_AI_API_KEY` | Optional | Gemma 4 via Google AI Studio |
| `XAI_API_KEY` | Optional | Grok models |
| `OPENAI_API_KEY` | Optional | GPT-4o, Whisper, TTS |
| `ELEVENLABS_API_KEY` | Optional | ElevenLabs TTS |
| `DEEPGRAM_API_KEY` | Optional | Deepgram STT |
| `STRIPE_SECRET_KEY` | Optional | Billing integration |
| `ORCHESTRA_API_KEY` | Optional | Auth for Architecture E server |
| `BROWSER_MODE` | Optional | `local`, `remote_cdp` (default: `local`) |
| `BROWSER_REMOTE_URL` | Optional | Remote CDP endpoint URL |
| `BROWSER_HEADLESS` | Optional | `true`/`false` (default: `true`) |
| `ORCHESTRA_DATA_DIR` | Optional | Data directory for memory/tasks (default: `~/.orchestra`) |

---

## License

MIT — see [LICENSE](LICENSE) for details.
