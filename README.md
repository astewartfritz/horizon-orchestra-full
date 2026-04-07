# Horizon Orchestra

> The most capable open agentic AI harness — built around Kimi K2.5 with five orchestration architectures, a non-blocking browser, cloud GPU integration, OS-level sandboxing, and full-stack multi-language infrastructure.

```
horizon run "Build me a financial dashboard for AAPL" --arch C
```

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    Horizon Orchestra                             │
│                                                                  │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│   │ Arch A   │  │ Arch B   │  │ Arch C   │  │ Arch D   │       │
│   │Monolithic│  │  RAG     │  │  Swarm   │  │   MCP    │       │
│   │          │  │ Pipeline │  │ (100 agt)│  │ Tool Hub │       │
│   └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
│        └─────────────┴─────────────┴──────────────┘             │
│                              │                                   │
│                    ┌─────────▼─────────┐                        │
│                    │   Architecture E   │                        │
│                    │ Production Stack   │                        │
│                    │  (wraps A/B/C/D)   │                        │
│                    └─────────┬─────────┘                        │
│                              │                                   │
│   ┌──────────────────────────▼────────────────────────────┐     │
│   │  MILES  ·  Memory  ·  AdaptiveContext  ·  LongHorizon │     │
│   │  TokenStreaming  ·  Safety  ·  Billing  ·  Skills      │     │
│   └───────────────────────────────────────────────────────┘     │
│                                                                  │
│   ┌─────────┐  ┌─────────┐  ┌────────────┐  ┌──────────────┐  │
│   │Frontier │  │  Cloud  │  │  Sandbox   │  │  Embeddings  │  │
│   │Browser  │  │  GPU    │  │  (4 OS)    │  │   Service    │  │
│   └─────────┘  └─────────┘  └────────────┘  └──────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

### Five Orchestration Architectures
| Arch | Name | Best For | Model | Cost |
|------|------|----------|-------|------|
| **A** | Monolithic Orchestrator | Single-agent tasks, 300 tool calls | Kimi K2.5 | 1.0× |
| **B** | RAG Pipeline | Web research, citations, multi-hop | Kimi K2.5 Thinking | 2.5× |
| **C** | Agent Swarm | Parallel tasks, up to 100 sub-agents | Kimi K2.5 | 5.0× |
| **D** | MCP Tool Hub | Dynamic tool discovery, 5-8 tools/agent | Kimi K2.5 | 3.0× |
| **E** | Production Stack | Full deployment wrapping A/B/C/D | Any | 1.2× overhead |

### MILES — Personal AI Layer
- Voice + awareness + routines + intelligence
- Persistent memory across sessions (semantic search)
- Adaptive context window (262K tokens, auto-compresses at 80%)
- Long-horizon tasks (checkpoint/resume, up to 4-hour workflows)
- Real-time SSE + WebSocket token streaming

### Frontier Browser
Non-blocking browser automation — agents work in sandboxed async environments while you continue browsing:
- DOM interpreter → typed objects (buttons→callables, forms→assignables)
- Shared context store across all agents
- Up to 10 concurrent sandbox environments
- Dual-channel events: SSE (sidebar) + WebSocket (automation feed)
- Prompt injection defense, rate limiting, approval workflow

### Cloud GPU Integration
Connects to the strongest available hardware:
| GPU | VRAM | Provider | Price |
|-----|------|----------|-------|
| GB200 NVL72 | 13.8 TB (72 GPUs) | CoreWeave, OCI | Contact |
| B200 | 192 GB | Lambda, CoreWeave | $4.62-6.99/hr |
| H200 | 141 GB HBM3e | AWS P5e, Lambda | $4.98/hr |
| H100 SXM5 | 80 GB HBM3 | Spheron, Lambda | $0.99-2.49/hr |
- Intelligent autoscaler: prefers cheapest provider, handles spot interruptions
- Inference router with 6 strategies (lowest latency, cost, GPU affinity, etc.)

### OS-Level Sandboxing
Production-grade isolation for 4 OS targets:
| OS | Packages | Native Sandbox |
|----|----------|----------------|
| Debian 11 (Bullseye) | 59,913 | AppArmor + seccomp-BPF |
| Fedora 37 | 66,166 | SELinux + seccomp-BPF |
| OpenBSD 7.3 | 7,787 | pledge + unveil |
| FreeBSD 13.2 | 30,766 | Capsicum + jail |
- Linux namespace isolation (PID, NET, MNT, USER, UTS, IPC)
- cgroup v2 resource limits (memory, CPU, PIDs, I/O)
- OverlayFS, tmpfs, path masking, minimal /dev
- 368 x86_64 syscall mappings, 4 seccomp profiles

### Billing — Stripe Integration
Architecture-aware pricing with 4 tiers:
| Tier | Price | Architectures | Long-Horizon |
|------|-------|---------------|--------------|
| Free | $0 | A only | — |
| Pro | $20/mo | A + B (RAG) | 1 hour |
| Team | $25/seat | A + B + C (Swarm) | 2 hours (3 concurrent) |
| **Max** | **$250/mo** | **All A–E** | **4 hours (10 concurrent)** |

### Mobile PWA
Full iPhone + Android support:
- Installable PWA with manifest, service worker
- Offline queue with IndexedDB (50MB, LRU eviction)
- Push notifications (VAPID, iOS Safari compat)
- Touch UI: swipe gestures, bottom nav, safe area insets, voice input

### Finance Terminal
25 tools across 7 modules — Bloomberg/Koyfin style:
- Real-time quotes, historical data, options chains
- Portfolio analysis, risk metrics, earnings calendar
- Macro indicators, crypto, FX

---

## Quick Start

```bash
# Install
pip install -e ".[all]"

# Or minimal install
pip install -e "."

# Run a task
horizon run "Research the latest AI model releases" --arch B

# Start the API server
horizon serve --port 8000

# Use a specific architecture
horizon run "Build a React dashboard" --arch C --model kimi-k2.5
```

### Docker
```bash
docker compose up -d
# API: http://localhost:8000
# Node bridge: http://localhost:3001
```

### Environment Variables
```bash
OPENAI_API_KEY=...          # For OpenAI models
MOONSHOT_API_KEY=...        # For Kimi K2.5
PERPLEXITY_API_KEY=...      # For Sonar retrieval (Arch B)
STRIPE_SECRET_KEY=...       # Billing
JWT_SECRET=...              # API auth
AWS_ACCESS_KEY_ID=...       # Cloud deployment
```

---

## Module Index

### Core Orchestration (`orchestra/`)
| Module | Description |
|--------|-------------|
| `arch_a.py` | Monolithic orchestrator |
| `arch_b.py` | RAG pipeline (Sonar → Kimi synthesis) |
| `arch_c.py` | Agent swarm (100 parallel sub-agents) |
| `arch_d.py` | MCP tool hub (dynamic tool discovery) |
| `arch_e.py` | Production stack (wraps A/B/C/D) |
| `router.py` | Model routing (Kimi, GPT, Claude, Gemini) |
| `memory.py` | Persistent cross-session memory |
| `agent_loop.py` | Tool registry + execution loop |
| `adaptive_context.py` | 262K token window management |
| `long_horizon.py` | Multi-hour task checkpoint/resume |
| `token_streaming.py` | SSE + WebSocket token streaming |
| `perplexity.py` | Sonar API retrieval |

### MILES (`orchestra/miles/`)
Personal AI assistant layer — intelligence, voice, awareness, routines

### Frontier Browser (`orchestra/frontier/`)
| Module | Description |
|--------|-------------|
| `dom_interpreter.py` | Typed DOM objects (buttons→callables) |
| `context_store.py` | Shared state across all agents |
| `sandbox.py` | Isolated browser execution environments |
| `task_runner.py` | Non-blocking async task orchestration |
| `agent_bridge.py` | LLM → browser RPC dispatch |
| `safety.py` | URL blocking, injection defense, approval flow |

### Cloud (`orchestra/cloud/`)
| Module | Description |
|--------|-------------|
| `compute.py` | Abstract compute backend |
| `lambda_runtime.py` | AWS Lambda execution |
| `terafab.py` | Terafab custom infrastructure |
| `gpu_providers.py` | 7 GPU providers, 10 GPU specs, real pricing |
| `gpu_cluster.py` | Multi-node cluster management |
| `autoscaler.py` | Cross-provider intelligent scaling |
| `inference_router.py` | Model inference routing |
| `websocket_relay.py` | Real-time WebSocket relay |
| `files.py` | S3 file storage |
| `sessions.py` | DynamoDB session persistence |

### Sandbox (`orchestra/sandbox/`)
| Module | Description |
|--------|-------------|
| `os_profiles.py` | Debian/Fedora/OpenBSD/FreeBSD profiles |
| `namespaces.py` | Linux namespace isolation + cgroup v2 |
| `seccomp.py` | 368-entry syscall table, BPF profiles |
| `filesystem.py` | OverlayFS, tmpfs, path masking |
| `network.py` | Network namespaces, iptables, DNS filter |
| `runtime.py` | Multi-OS hardened sandbox runtime |

### Billing (`orchestra/billing/`)
Stripe integration + architecture-aware feature gating

### Media (`orchestra/media/`)
ffmpeg, yt-dlp, DALL-E/FLUX image gen, Veo/Sora video gen, TTS, Whisper STT

### Documents (`orchestra/documents/`)
PDF (WeasyPrint), PPTX (python-pptx), XLSX (openpyxl), Charts (matplotlib/plotly), Pandoc

### Embeddings (`orchestra/embeddings/`)
6 embedding models, HNSW vector index, pgvector, 5 chunking strategies, pipeline

### Connectors (`orchestra/connectors/`)
Gmail, GitHub, Slack, Notion, Linear, Snowflake, GCal, GDrive, Jira, HubSpot, Airtable, Stripe, AWS, Monday, MCP bridge

### Finance (`orchestra/finance/`)
25 tools: quotes, options, portfolio, risk, macro, crypto, FX

### Skills (`orchestra/skills/`)
11 Horizon Prince skills: data exploration, statistics, visualization, ML pipeline, SQL analytics, validation, research, documents, media, wide research, monitoring

---

## API

29 REST endpoints + WebSocket + SSE streaming. Full TypeScript SDK included.

```typescript
import { HorizonClient } from '@horizon-orchestra/sdk'

const client = new HorizonClient({ baseUrl: 'https://api.horizon-orchestra.com', token: '...' })

// Run a task
const result = await client.run({ task: 'Research OpenAI competitors', architecture: 'B' })

// Stream results
for await (const event of client.streamRun({ task: 'Build a dashboard' })) {
  if (event.type === 'token') process.stdout.write(event.data.content as string)
}
```

---

## Multi-Language Stack

```
horizon-orchestra/
├── orchestra/          # Python — 165 modules, 79,597 lines
├── sdk/                # TypeScript — Type-safe API client, 1,586 lines
├── node/               # TypeScript — Node.js bridge server, 1,798 lines
├── go/envd/            # Go — Sandbox manager (envd), gRPC, Firecracker
├── rust/orchestra-core/ # Rust — Tokenizer, HNSW index, BPF compiler
├── scripts/            # Shell — Bootstrap, health, deploy, backup
└── tests/              # Python — 268 test functions
```

---

## Pricing

| Tier | Monthly | Per Year |
|------|---------|----------|
| Free | $0 | $0 |
| Pro | $20 | $204 |
| Team | $25/seat | $255/seat |
| **Max** | **$250** | **$2,500** |

---

## License

MIT — see [LICENSE](LICENSE)

---

Built by [Ashton Fritz](https://github.com/astewartfritz) · [horizon-orchestra.com](https://horizon-orchestra.com)
