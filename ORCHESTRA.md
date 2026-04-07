# Horizon Orchestra — Project Conventions

## Architecture Map

```
orchestra/
├── __init__.py              # Package exports (all modules)
├── router.py                # Multi-model registry + intelligent routing (20+ models)
├── agent_loop.py            # Core async agent loop with tool calling
├── gemma4_provider.py       # Gemma 4 native provider (thinking, multimodal, function calling)
├── arch_a.py                # Architecture A — Monolithic Orchestrator
├── arch_c.py                # Architecture C — Native Agent Swarm
├── arch_e.py                # Architecture E — Full Production Stack
├── cli.py                   # Unified CLI for all architectures + Gemma 4 tools
├── memory.py                # Persistent memory: SQLite + embeddings + auto-extraction
├── perplexity.py            # Sonar search + Agent API + multi-model council
└── swarm.py                 # DAG-based parallel sub-agent execution
```

## Backbone Models

Horizon Orchestra uses dual backbone models with intelligent routing:

### Kimi K2.5 (Primary)
- **Provider:** Moonshot, OpenRouter, Together, local vLLM
- **Context:** 262K tokens
- **Strengths:** 200-300 stable sequential tool calls, agentic reasoning, coding
- **Cost:** $0.60/$2.50 per 1M tokens (input/output)

### Gemma 4 (Secondary — Apache 2.0)
Four variants registered across 9 endpoints:

| Variant | Params | Context | Architecture | Strengths | Cost |
|---------|--------|---------|-------------|-----------|------|
| **31B** | 30.7B | 256K | Dense | Reasoning, coding, agentic, vision, tool use | $0.15/$0.60 |
| **26B MoE** | 25.2B (3.8B active) | 256K | MoE | Speed + reasoning, vision, tool use | $0.10/$0.40 |
| **E4B** | 4.5B effective | 128K | Efficient | On-device, vision, audio, lightweight | Free |
| **E2B** | 2.3B effective | 128K | Efficient | On-device, audio, ultra-lightweight | Free |

Each variant available via: Gemini API, OpenRouter, local vLLM, Ollama.

### Gemma 4 Capabilities
- **Thinking mode:** Configurable thinking budget for step-by-step reasoning (31B, 26B, E4B)
- **Native function calling:** Structured tool use built into the model
- **Vision:** Images, video frames, OCR, chart understanding (all variants)
- **Audio:** ASR, speech translation (E2B, E4B only)
- **System prompt:** Native `system` role support
- **Multilingual:** 140+ languages
- **License:** Apache 2.0 (full commercial freedom)

## Python Standards

- **Version:** 3.11+
- **Async everywhere:** All I/O uses `async/await`
- **Type hints required:** Every function signature has full type annotations
- **Imports:** Use `from __future__ import annotations` in every module
- **Import guards:** `try/except ImportError` for optional dependencies (`google-genai`, `fastapi`, `boto3`)
- **Error handling:** Never silently swallow exceptions; log and re-raise or return structured errors

## Naming Conventions

- **Modules:** `snake_case.py`
- **Classes:** `PascalCase`
- **Functions/methods:** `snake_case`
- **Constants:** `UPPER_SNAKE_CASE`
- **Private:** `_single_underscore` prefix
- **Model names:** `gemma-4-31b`, `kimi-k2.5` (kebab-case in registry)

## Connector Pattern

Every external service connector follows:
```python
class MyConnector(Connector):
    name = "my_service"
    description = "..."

    async def connect(self, credentials: dict[str, str]) -> bool: ...
    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]: ...
    def get_tool_definitions(self) -> list[dict[str, Any]]: ...
```

## Model Selection Guide

| Task | Recommended Model | Rationale |
|------|------------------|-----------|
| Complex coding | `kimi-k2.5` or `gemma-4-31b` | Best reasoning + tool stability |
| Fast parallel agents | `gemma-4-26b-moe` | 3.8B active params = fast inference |
| Web research | `sonar-pro` | Citation-grounded search |
| Quick summaries | `grok-3` | Fast + cheap |
| On-device / edge | `gemma-4-e4b` or `gemma-4-e2b` | Runs on phones + Raspberry Pi |
| Vision / OCR | `gemma-4-31b` | Best vision quality |
| Audio transcription | `gemma-4-e4b` | Native audio input |
| Cost-optimised bulk | `gemma-4-26b-moe` | $0.10/$0.40 with strong quality |

## Dependencies

### Required
- `openai` — AsyncOpenAI client for all OpenAI-compatible providers
- `httpx` — HTTP client for tool implementations

### Optional
- `google-genai` — Native Gemma 4 / Gemini SDK (thinking, multimodal, audio)
- `fastapi` + `uvicorn` — Architecture E production server
- `playwright` — Browser automation
- `boto3` — AWS integrations

## CLI Quick Reference

```bash
# Run with Gemma 4
python -m orchestra.cli run "Build an API" --arch A --model gemma-4-31b
python -m orchestra.cli run "Research + build" --arch C --model gemma-4-26b-moe

# Architecture E server
python -m orchestra.cli serve --model gemma-4-31b --port 3000

# Gemma 4 tools
python -m orchestra.cli gemma4 info --model gemma-4-31b
python -m orchestra.cli gemma4 modelfile --variant 31b
python -m orchestra.cli gemma4 vllm --variant 31b --gpus 1

# Memory
python -m orchestra.cli memory search "What am I building?"
python -m orchestra.cli memory store "I prefer Gemma 4" --category preference

# Docker
python -m orchestra.cli docker
```

## Local Deployment

### Ollama (easiest)
```bash
python -m orchestra.cli gemma4 modelfile --variant 31b
ollama create gemma4-orchestra -f Modelfile
python -m orchestra.cli run "Hello" --model gemma-4-ollama
```

### vLLM (production)
```bash
python -m orchestra.cli gemma4 vllm --variant 31b --gpus 1
# Starts: vllm serve google/gemma-4-31B-it --tensor-parallel-size 1 ...
python -m orchestra.cli run "Hello" --model gemma-4-31b-local
```

### Docker Compose (full stack)
```bash
python -m orchestra.cli docker
docker compose up -d
# Spins up: Kimi vLLM + Gemma 4 vLLM + API gateway + PostgreSQL + Redis
```

---

## Claude / Anthropic Model Family

### Models Available

| Model | Registry Key | Context | Max Output | Cost (in/out per 1M) | Strengths |
|---|---|---|---|---|---|
| Claude Opus 4.6 | `claude-opus-4.6-openrouter` | 1M | 128K | $5 / $25 | Peak reasoning, coding, agentic, vision, long-context |
| Claude Opus 4.6 (native) | `claude-opus-4.6-native` | 1M | 128K | $5 / $25 | Same + adaptive thinking via native SDK |
| Claude Sonnet 4.6 | `claude-sonnet-4.6-openrouter` | 1M | 64K | $3 / $15 | Near-Opus quality, 5x cheaper, balanced |
| Claude Haiku 4.5 | `claude-haiku-4.5-openrouter` | 200K | 8K | $1 / $5 | Speed, high-volume, cost-efficient |

### Native vs OpenRouter
- **OpenRouter variants** (`*-openrouter`) use the OpenAI-compatible API — works with the standard `ModelRouter.get_client()` path. Use for standard chat completions and tool calling.
- **Native variants** (`*-native`) require `opus4_provider.Opus4Provider` for extended thinking, vision, streaming, and interleaved tool use. Calling `router.get_client()` on a native variant raises a `ValueError` directing you to the provider.

### Adaptive Thinking
Opus 4.6 and Sonnet 4.6 use **adaptive thinking** — the model decides when deep reasoning is helpful. Configure via effort levels:

```python
from orchestra.opus4_provider import Opus4Provider, Opus4Config

config = Opus4Config(model="claude-opus-4.6-native", effort="high")
provider = Opus4Provider(config=config)

# Adaptive thinking with effort control
response = await provider.think(
    prompt="Refactor this payment service for idempotency",
    system_prompt="You are a senior backend engineer.",
    effort="max",  # low | medium | high (default) | max
)
print(response.thinking_summary)  # summarized reasoning chain
print(response.answer)            # final answer
```

Effort levels:
- **low** — fast responses, minimal thinking (budget: 1024 tokens)
- **medium** — moderate reasoning (budget: 8192 tokens)  
- **high** (default) — deep reasoning when helpful (budget: 16384 tokens)
- **max** — maximum reasoning effort (budget: 32768 tokens)

### Interleaved Thinking
Opus 4.6 automatically reasons *between* tool calls — no beta header needed. When using `function_call()`, the model will:
1. Think about the task
2. Call a tool
3. Think about the result
4. Decide next action
5. Repeat

This is automatic with adaptive thinking enabled.

### Vision Capabilities
Process up to 600 images or PDF pages per request:

```python
from orchestra.opus4_provider import Opus4Provider, VisionInput

provider = Opus4Provider()
result = await provider.vision(
    inputs=[
        VisionInput(type="image_url", content="https://example.com/chart.png", mime_type="image/png"),
        VisionInput(type="pdf_bytes", content=pdf_bytes, mime_type="application/pdf"),
        VisionInput(type="text", content="Analyze these financial documents"),
    ],
    model="claude-opus-4.6-native",
)
```

### Context Compaction
For ultra-long sessions, enable auto-summarization of older context:

```python
config = Opus4Config(enable_compaction=True)
provider = Opus4Provider(config=config)
# Claude will auto-summarize when approaching context limits
```

---

## Security Model

Orchestra implements a 5-layer defense-in-depth security architecture in `orchestra/security.py`.

### Layer 1: Permission Boundaries

```python
from orchestra.security import PermissionPolicy, strict_policy, standard_policy

# Use a preset
policy = strict_policy()

# Or customize
policy = PermissionPolicy(
    allowed_tools={"web_search", "file_read", "memory_search"},
    denied_domains={"internal.corp.com", "169.254.169.254"},
    require_confirmation_for={"gmail_send", "slack_post"},
    max_tool_calls=100,
    credential_ttl_seconds=900,  # 15-minute JIT tokens
)
```

Preset policies:
| Policy | Tool Access | Confirmation Gates | File Write | Network | Use Case |
|---|---|---|---|---|---|
| `strict_policy()` | Allowlisted only | All destructive ops | Restricted paths | Filtered | Untrusted input, public-facing |
| `standard_policy()` | All except denied | Send/post/delete | Workspace only | Filtered | General production use |
| `permissive_policy()` | Unrestricted | None | Unrestricted | Open | Trusted internal use |
| `safety_critical_policy()` | Highly restricted | All external ops | Read-only | Restricted | Financial, medical, legal |

### Layer 2: Input Sanitization
Detects and neutralizes prompt injection attempts:
- Instruction override patterns ("ignore previous instructions")
- Role injection ("you are now", "act as")
- System prompt markers ("[SYSTEM]", "<<SYS>>")
- Base64-encoded instruction payloads
- Unicode homoglyph attacks (RTL override, zero-width characters)
- HTML comment injection
- JavaScript URL injection
- Data exfiltration patterns

### Layer 3: Output Monitoring
Real-time behavioral analysis:
- **Loop detection** — flags if the same tool is called 5+ times consecutively
- **Data exfiltration** — detects sensitive data being encoded in outbound URLs
- **Credential leakage** — catches API keys, tokens appearing in output (sk-, ghp_, xoxb-, AIza, AKIA, etc.)
- **PII detection** — email, phone, SSN, credit card patterns with automatic redaction
- **Behavioral discontinuity** — flags unexpected tool use that doesn't match the task

### Layer 4: Rate Limiting
Token-bucket rate limiting:
```python
from orchestra.security import RateLimiter

limiter = RateLimiter(
    max_requests_per_minute=60,
    max_tokens_per_minute=1_000_000,
)
```

### Layer 5: Security Middleware Integration
The middleware wraps every tool execution in the agent loop:

```python
from orchestra.arch_a import MonolithicAgent, MonolithicConfig

# Security enabled by default
agent = MonolithicAgent(config=MonolithicConfig(
    model="claude-opus-4.6-openrouter",
    enable_security=True,
    security_policy="strict",
))

# Tool calls are now:
# 1. Permission-checked (is this tool allowed?)
# 2. Input-sanitized (are arguments safe?)
# 3. Rate-limited (within budget?)
# 4. Executed (if all checks pass)
# 5. Output-monitored (PII redacted, exfil blocked)
# 6. Audit-logged (full trail)
```

### Audit Trail
Every security decision is logged:
```python
audit = agent.security.get_audit_log()
# [{"timestamp": 1712505600, "tool": "web_search", "action": "pre_execution", "allowed": True, "alerts": []}, ...]
```

---

## Domain Router

Automatic task-to-model routing based on domain classification.

### Domains

| Domain | Primary Models | Effort | Security | Temperature |
|---|---|---|---|---|
| `coding` | Opus 4.6 → Gemma 4 31B → Kimi K2.5 | high | strict | 0.3 |
| `research` | Opus 4.6 → Sonar Reasoning Pro → Sonnet 4.6 | high | standard | 0.5 |
| `creative` | Opus 4.6 → Sonnet 4.6 → Kimi K2.5 | medium | permissive | 0.9 |
| `data_analysis` | Sonnet 4.6 → Gemma 4 31B → Opus 4.6 | high | standard | 0.2 |
| `safety_critical` | Opus 4.6 only | max | safety_critical | 0.1 |
| `general` | Sonnet 4.6 → Gemma 4 26B MoE → Kimi K2.5 | medium | standard | 0.6 |

### Usage

```python
from orchestra.domain_router import DomainRouter
from orchestra.router import ModelRouter

dr = DomainRouter(router=ModelRouter())

# Classify a task
classification = dr.classify("Refactor the payment service for idempotency")
# TaskClassification(domain="coding", confidence=0.85, subdomain="refactoring", ...)

# Get optimal route
route = dr.route(classification, cost_ceiling=30.0)
# DomainRoute(model="claude-opus-4.6-openrouter", effort="high", policy="strict", ...)

# One-shot convenience
route = dr.route_task("Analyze Q4 revenue data and create visualizations")
# DomainRoute(model="claude-sonnet-4.6-openrouter", effort="high", policy="standard", ...)
```

### Cost Ceilings
Pass `cost_ceiling` (max $/1M output tokens) to automatically fall back to cheaper models:
```python
route = dr.route_task("Write a blog post about AI safety", cost_ceiling=10.0)
# Will prefer Sonnet 4.6 ($15 output) or Gemma 4 ($0.60 output) over Opus 4.6 ($25 output)
```

---

## Speech & Audio

Orchestra provides unified speech-to-text (STT) and text-to-speech (TTS) through `speech_provider.py`, with 6 STT backends and 6 TTS backends available.

### STT Backends

| Backend | Provider | Languages | Real-time | Diarization | Cost | Best For |
|---|---|---|---|---|---|---|
| `whisper_api` | OpenAI | 50+ | No | No | $0.006/min | Reliable general-purpose STT |
| `deepgram` | Deepgram | 36+ | Yes (<300ms) | Yes | $0.0077/min | Real-time streaming, voice agents |
| `assemblyai` | AssemblyAI | 99+ | Yes | Yes | Varies | Audio intelligence, sentiment, PII redaction |
| `groq_whisper` | Groq | 50+ | No | No | $0.04/hr | Ultra-cheap batch transcription |
| `elevenlabs_scribe` | ElevenLabs | 90+ | Yes | No | $0.40/hr+ | 98%+ accuracy, dynamic audio tagging |
| `whisper_local` | Self-hosted | 50+ | No | No | Free | Privacy, offline, no API costs |

### TTS Backends

| Backend | Provider | Languages | Voice Clone | Latency | Cost | Best For |
|---|---|---|---|---|---|---|
| `openai_tts` | OpenAI | 50+ | No | ~500ms | $15/1M chars | Simple integration, 10 built-in voices |
| `elevenlabs` | ElevenLabs | 74+ | Yes (30min) | ~75-300ms | $0.08-0.12/1K chars | Highest polish, 10K+ voices, production audio |
| `kokoro` | Local (Apache 2.0) | 6 | No | <10ms | Free | Edge/CPU deployment, 82M params, MOS 4.5 |
| `fish_speech` | Fish Audio | 80+ | Yes (3-10s) | <150ms | Free (self-host) | Emotion control (15K+ tags), multilingual |
| `chatterbox` | Resemble AI (MIT) | 1 | Yes (5s) | <150ms | Free | Voice cloning, beats ElevenLabs in blind tests |
| `deepgram_aura` | Deepgram | 7 | No | <200ms | $30/1M chars | Low-latency voice agents, unified STT+TTS |

### Usage — Transcription

```python
from orchestra.speech_provider import SpeechProvider, STTConfig, STTBackend

provider = SpeechProvider()

# Default (Whisper API)
result = await provider.transcribe("/path/to/audio.mp3")
print(result.text)

# Deepgram with speaker diarization
result = await provider.transcribe(
    audio_bytes,
    config=STTConfig(
        backend=STTBackend.DEEPGRAM,
        enable_diarization=True,
    ),
)
for speaker in result.speakers:
    print(f"[{speaker.speaker}] {speaker.text}")

# Local Whisper (no API costs)
result = await provider.transcribe(
    audio_bytes,
    config=STTConfig(backend=STTBackend.WHISPER_LOCAL),
)
```

### Usage — Text-to-Speech

```python
from orchestra.speech_provider import SpeechProvider, TTSConfig, TTSBackend, AudioFormat

provider = SpeechProvider()

# OpenAI TTS
result = await provider.synthesize(
    "Hello, this is Orchestra speaking.",
    config=TTSConfig(backend=TTSBackend.OPENAI_TTS, voice="nova"),
)
with open("output.mp3", "wb") as f:
    f.write(result.audio_data)

# Fish Speech with emotion control
result = await provider.synthesize(
    "[excited]We just shipped the feature![/excited] [calm]Let me walk you through it.[/calm]",
    config=TTSConfig(backend=TTSBackend.FISH_SPEECH, emotion="dynamic"),
)

# Kokoro (free, local, CPU-viable)
result = await provider.synthesize(
    "Processing complete. Results are ready.",
    config=TTSConfig(backend=TTSBackend.KOKORO, voice="af_heart"),
)

# Voice cloning with Chatterbox
result = await provider.synthesize(
    "This will sound like the reference speaker.",
    config=TTSConfig(
        backend=TTSBackend.CHATTERBOX,
        voice_clone_audio=reference_audio_bytes,  # 5s sample
    ),
)
```

### Agent Tools

Audio tools are automatically registered in the agent loop. Agents can call:

| Tool | Description |
|---|---|
| `transcribe_audio` | Transcribe an audio file to text with backend selection |
| `synthesize_speech` | Generate speech from text with voice/emotion control |
| `analyze_audio` | Get audio file metadata and cost estimates |
| `clone_voice` | Clone a voice from reference audio and generate speech |
| `translate_speech` | Translate foreign language speech to English |
| `list_audio_backends` | List all available STT/TTS backends with capabilities |

### Docker Deployment

The Docker Compose stack includes optional local speech services:

```bash
# Start with local TTS/STT
docker compose up kokoro fish-speech whisper-local

# Kokoro: http://localhost:8880 (OpenAI-compatible, Apache 2.0)
# Fish Speech: http://localhost:8080 (80+ languages, emotion tags)
# Whisper Local: http://localhost:8787 (faster-whisper, GPU accelerated)
```

### Cost Optimization

| Volume | Recommended STT | Recommended TTS |
|---|---|---|
| < 100 hrs/mo | Whisper API ($36) or Groq ($4) | OpenAI TTS or ElevenLabs Flash |
| 100-500 hrs/mo | Deepgram Nova-3 ($46-231) | ElevenLabs or Kokoro (local) |
| 500+ hrs/mo | Self-hosted Whisper (free) | Kokoro or Fish Speech (free) |
| Real-time | Deepgram streaming | Kokoro or Deepgram Aura |

---

## Pricing & Billing

Orchestra includes a full Stripe billing integration in `stripe_billing.py` and `usage_tracker.py` for monetizing your Orchestra-powered platform.

### Pricing Tiers

| Feature | Maker ($0) | Builder ($29) | Pro ($99) | Enterprise ($499) |
|---|---|---|---|---|
| **Models** | Gemma 4 E4B/E2B, local only | + Gemma 4 31B/26B, Kimi K2.5, Sonar, Grok | + Claude Opus/Sonnet/Haiku, GPT-5.4 | All + fast mode |
| **Architectures** | A (monolithic) | A + C (swarm, 5 agents) | A + C + E (production) | All + custom |
| **STT** | Local Whisper only | + Whisper API, Deepgram, Groq | All 6 backends | All |
| **TTS** | Kokoro, Chatterbox | + OpenAI TTS, Fish Speech | All 6 backends | All + voice cloning |
| **Security** | Standard | + Strict | All including safety-critical | All + custom policies |
| **Domain Router** | No | No | Yes | Yes |
| **Tool Calls/mo** | 1,000 | 50,000 | 500,000 | Unlimited |
| **STT Minutes/mo** | 60 | 600 | 6,000 | Unlimited |
| **TTS Minutes/mo** | 30 | 120 | 1,200 | Unlimited |
| **Model Credit** | $0 | $10 | $50 | $200 |
| **Memory Entries** | 100 | 5,000 | 50,000 | Unlimited |

### Usage-Based Overages

Beyond included limits, pass-through costs apply with markup:
- LLM tokens: actual model cost + 30% markup
- STT/TTS: actual backend cost + 25% markup
- Extra tool calls: $0.001 each
- Extra swarm spawns: $0.01 each

### Integration

```python
from orchestra.stripe_billing import BillingManager, PricingTier
from orchestra.usage_tracker import UsageTracker

# Initialize billing
billing = BillingManager()  # uses STRIPE_SECRET_KEY env var

# Create customer
customer = await billing.create_customer(
    email="user@example.com",
    name="Dev Team",
    tier=PricingTier.PRO,
)

# Create usage tracker for agent sessions
tracker = UsageTracker(
    billing=billing,
    customer_id=customer.stripe_customer_id,
    tier=PricingTier.PRO,
)

# Wire into agent
config = AgentConfig(model="claude-opus-4.6-openrouter", usage_tracker=tracker)
```

### Stripe Meters

9 billing meters track all usage dimensions:

| Meter | Event Name | Unit |
|---|---|---|
| LLM Input | `orchestra_llm_input_tokens` | tokens |
| LLM Output | `orchestra_llm_output_tokens` | tokens |
| Tool Calls | `orchestra_tool_calls` | count |
| Swarm Spawns | `orchestra_swarm_spawns` | count |
| STT | `orchestra_stt_seconds` | seconds |
| TTS | `orchestra_tts_characters` | characters |
| Memory | `orchestra_memory_entries` | count |
| Code Exec | `orchestra_code_executions` | count |
| Browser | `orchestra_browser_actions` | count |

### API Endpoints

```
POST /v1/billing/customers          — Create a billing customer
GET  /v1/billing/customers/{id}/usage — Get usage summary
GET  /v1/billing/customers/{id}/budget — Get remaining budget
GET  /v1/billing/tiers              — List pricing tiers
```

---

## Perplexity Computer Parity Features

Orchestra now implements the core architectural touchpoints of Perplexity Computer.

### Skills System

Skills are reusable instruction sets that auto-activate based on task content — the same pattern Perplexity Computer uses for its built-in Research, Slides, and Data Analysis skills.

**8 Built-in Skills:**

| Skill | Triggers | Chains To |
|---|---|---|
| `research` | research, investigate, analyze, deep-dive | slides, research-report |
| `slides` | presentation, slides, deck, PowerPoint | research |
| `data-analysis` | CSV, dataset, statistics, chart, visualize | research-report |
| `code-review` | review code, PR review, find bugs, audit | — |
| `writing` | write, draft, blog post, article, email | — |
| `executive-summary` | TL;DR, summarize, key points, brief | — |
| `debugging` | debug, fix, error, traceback, broken | — |
| `competitor-analysis` | competitor, vs, benchmark, market research | slides |

**Usage:**
```python
from orchestra.skills import SkillRegistry, SkillActivator

registry = SkillRegistry.default()

# Auto-match skills to a task
matches = registry.match("Research the top 5 CRMs and build a comparison deck")
# -> [SkillMatch(skill=research, score=0.85), SkillMatch(skill=slides, score=0.72)]

# Build enriched system prompt
enriched_prompt = registry.build_system_prompt(matches, base_prompt="You are Orchestra...")

# Agent integration (auto-wired in Arch A and C)
agent = MonolithicAgent(config=MonolithicConfig(
    model="claude-opus-4.6-openrouter",
    enable_skills=True,   # default
))
```

**Custom Skills (SKILL.md format):**
```markdown
---
name: weekly-digest
description: Use when asked to create a weekly summary or digest report
version: "1.0"
tools_required: [web_search, memory_search, file_write]
models_preferred: [claude-sonnet-4.6]
chains_to: [executive-summary]
---

# Weekly Digest Skill

When creating a weekly digest:
1. Search for the week's top stories in the specified domain
2. Check memory for previously reported items to avoid duplication
3. Structure as: Top Stories → Key Trends → Notable Quotes → Next Week Preview
4. Keep each item to 2-3 sentences maximum
5. Save to workspace/digests/{date}.md
```

Save custom skills to `~/.horizon/skills/` or upload via the API:
```
POST /v1/skills/upload   — Upload a .md or .zip skill file
GET  /v1/skills          — List all skills
POST /v1/skills/match    — Find skills matching a task
```

### Model Council

Run multiple frontier models in parallel, then synthesize where they agree and disagree — directly mirroring Perplexity Computer's Model Council feature.

```python
from orchestra.model_council import ModelCouncil

council = ModelCouncil(router=ModelRouter())

result = await council.deliberate(
    prompt="Should we migrate from PostgreSQL to DynamoDB for our user table?",
    models=["claude-opus-4.6-openrouter", "gemma-4-31b", "kimi-k2.5"],
    orchestrator="claude-opus-4.6-openrouter",
)

print(result.consensus)           # synthesized answer
print(result.divergence_points)   # where models disagreed
print(result.agreement_score)     # 0.0-1.0 how much they agreed
print(result.to_markdown())       # full formatted report
```

Three modes:
- **Deliberate** — full synthesis with divergence analysis (default)
- **Vote** — simple majority vote on a list of options
- **Debate** — multi-round where models can respond to each other

The `council_deliberate` tool is automatically registered in the agent loop so agents can invoke Model Council as a tool.

API endpoint: `POST /v1/council`

### Persistent Tasks

Long-running, pauseable, schedulable tasks with filesystem-based IPC between sub-agents. Mirrors Perplexity's architecture where tasks run for hours or months.

```python
from orchestra.tasks import TaskManager, TaskSpec, Schedule

manager = TaskManager()

# One-shot task
task_id = await manager.submit(TaskSpec(
    name="Q1 Analysis",
    prompt="Analyze Q1 revenue and produce a board presentation",
    model="claude-opus-4.6-openrouter",
))

# Scheduled recurring task (daily at 8am)
task_id = await manager.submit(TaskSpec(
    name="Daily AI News Brief",
    prompt="Research today's top AI news and write a 5-point summary",
    schedule=Schedule(cron="0 8 * * *"),
))

# Lifecycle control
await manager.pause(task_id)
await manager.resume(task_id)
await manager.cancel(task_id)

# Human check-ins (agent gates)
pending = await manager.get_pending_checkins()
await manager.respond_to_checkin(task_id, checkin_id, "Yes, proceed")
```

**Filesystem IPC layout** (how sub-agents communicate — same pattern as Perplexity's Firecracker VM architecture):
```
/tmp/horizon_workspace/{task_id}/
    context.md              ← parent agent writes goal here
    agents/
        {agent_id}/
            task.md         ← sub-agent's assignment
            output.md       ← sub-agent writes results here
            status.json     ← progress tracking
    results/
        synthesis.md        ← parent synthesizes all outputs
    logs/
        {timestamp}.log     ← full execution log
```

### Citation Grounding

Every factual claim in agent responses is anchored to a verifiable source — Perplexity's core differentiator.

```python
from orchestra.citation import CitationTracker, CitationMiddleware

tracker = CitationTracker()
middleware = CitationMiddleware(tracker, enforce_citations=True)

# Sources auto-register as tools execute (web_search, fetch_url)
# Wired into AgentConfig automatically when enable_citations=True:
agent = MonolithicAgent(config=MonolithicConfig(
    enable_citations=True,
))

# Or use standalone:
grounded = middleware.ground_response(raw_response)
print(grounded.to_markdown())
# "According to Gartner, AI adoption grew 34% in 2025 [1]..."
# "## Sources\n[1] https://gartner.com/... — Gartner AI Report 2026"

print(grounded.citation_rate)    # fraction of factual claims cited
print(grounded.uncited_claims)   # claims with no source found
```

---

## CLI Reference (Updated)

```bash
# Gemma 4 commands (existing)
python -m orchestra.cli gemma4 info
python -m orchestra.cli gemma4 modelfile --variant 31b

# Opus 4.6 model info
python -m orchestra.cli models  # list all models including Claude family

# Architecture selection
python -m orchestra.cli run --arch A --model claude-opus-4.6-openrouter "Build a REST API"
python -m orchestra.cli run --arch C --model claude-opus-4.6-openrouter "Research and build a dashboard"
```
