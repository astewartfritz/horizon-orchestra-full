# Changelog

All notable changes to Horizon Orchestra are documented here.

---

## [0.5.0] — 2026-05-17

### Added — AgentMesh (P2P Agent Network)
- **AgentRegistry**: register/unregister/discover agents by capability, type, or tag; heartbeat + stale eviction; callbacks on register/unregister/status-change
- **AgentNode**: lifecycle (start/stop), custom message handlers per MessageType, LLM function injection
- **MeshNetwork**: broadcast, direct request, capability-routed request, delegate, full trace storage
- **MeshRouter**: multi-target routing with capability lookup
- **MeshMessage / MessageType**: typed protocol (REQUEST/RESPONSE/DELEGATE/HEARTBEAT/BROADCAST)
- **10 REST endpoints** at `/api/agentmesh/` — register, list, heartbeat, discover, message, request, health, traces
- **34 tests** passing

### Added — Teams & Swarm Coordination
- **TeamFactory**: task analysis → capability extraction → team formation with 3 built-in strategies
  - `BestFitStrategy` — highest-capability match per required skill
  - `LoadBalancedStrategy` — distributes load across available agents
  - `MinimumTeamStrategy` — smallest team that covers all capabilities
- **AgentTeam**: parallel member execution, leader-coordinated synthesis, add/remove members
- **TeamLeader**: delegates task to full team, returns synthesized result
- **SwarmCoordinator**: 4 swarm modes — consensus (multi-round voting), hierarchical (leader + sub-groups), collaborative (parallel subtasks), competitive (best-wins)
- **REST routes** at `/api/teams/` — form, execute, list, swarm/{consensus,hierarchical,collaborative,competitive}, analyze-task
- **28 tests** passing (+ uses agentmesh fixtures)

### Added — Channels v2 (Production Infrastructure)
- **ChannelHealthMonitor**: per-channel status tracking, latency averaging, consecutive failure counting, healthy/error/unknown states
- **OutputFormatter**: platform-aware message formatting for 7 channels (Slack bold→`*`, Telegram HTML, WhatsApp code strip, Email HTML, iMessage placeholder, Discord, default); custom formatter registration
- **ChannelRetryEngine**: 4 retry strategies (FIXED, EXPONENTIAL, LINEAR, JITTER) with per-channel config, async + sync callable support
- **MessageQueue**: priority queue (CRITICAL/HIGH/NORMAL/LOW), multi-worker pool, dead-letter queue with requeue, batch enqueue, per-channel stats
- **10 REST endpoints** at `/api/channels/v2/` — health, format, retry-config, enqueue, queue stats, DLQ, register-channel
- **34 tests** passing

### Added — Workflow v2 REST API
- **11 REST endpoints** at `/api/workflow-v2/` — CRUD workflows, run by ID, run direct (inline), list instances, get instance detail, resume human-handoff step, list step types
- Exposes full DAG Workflow Engine v2 (AgentStep, ToolStep, TransformStep, ParallelStep, ConditionStep, SwitchStep, LoopStep, HumanHandoffStep, SubWorkflowStep)

### Added — Reasoning REST API
- **6 REST endpoints** at `/api/reasoning/` — list strategies, get strategy + system prompt, select strategy (auto), analyze task signals, start session, list/get traces
- Exposes auto strategy selection (CoT → PlanAndExecute → ReflectOnError based on task length + keywords)
- **23 tests** passing

### Added — Monitor & Alerting REST API
- **11 REST endpoints** at `/api/monitor/` — record metrics (counter/gauge/histogram), batch record, list/query/aggregate metrics, summary, prune, alert rules CRUD, alert check, alert history
- Backed by SQLite MetricsCollector + AlertManager with 4 condition types (gt/lt/gte/lte) and cooldown deduplication
- **25 tests** passing

### Added — Telemetry REST API
- **8 REST endpoints** at `/api/telemetry/` — start trace, start/end span, get trace detail, get summary, list active traces, delete trace, health
- Wraps AgentTracer singleton; spans include parent_id, attributes, duration_ms, status
- **16 tests** passing

### Stats
- **+143 new tests** (total 1535 passing)
- **+6 new REST route modules** (reasoning, monitor, telemetry, agentmesh, teams, channels/v2, workflow-v2)
- 5 new Python packages (`agentmesh`, `teams`, `reasoning/routes`, `monitor/routes`, `telemetry/routes`)

---

## [0.6.0] — 2026-05-17

### Added — Active Agents (autonomous agent drivers)
- **`ActiveAgent` ABC** — common interface: `execute(task, context) → AgentResult`, `health_check() → AgentHealthStatus`, `can_handle(intent)`, `to_dict()`
- **`AgentCapability`** — named capability with `intent_keywords` for keyword routing
- **`AgentResult`** — structured output with `success`, `output`, `error`, `duration_ms`, `metadata`
- **`AgentHealthStatus`** — per-agent health with `status` (AVAILABLE/DEGRADED/UNAVAILABLE/UNKNOWN), `version`, `latency_ms`
- **`ClaudeCodeAgent`** (priority=10) — spawns `claude --print --output-format text`; falls back to `anthropic.AsyncAnthropic` (claude-opus-4-7); capabilities: coding, file_ops, git, shell
- **`CodexAgent`** (priority=20) — spawns `codex --full-auto -q`; falls back to OpenAI Chat API (gpt-4o); capabilities: coding, refactor, explain
- **`OpenClawAgent`** (priority=30) — spawns `openclaw run --task`; falls back to Ollama (`codellama`); capabilities: coding, analysis, search, test
- **`ActiveAgentRegistry`** — register/unregister agents, priority-sorted discovery, intent-based and capability-based lookup, concurrent health checks, `execute_with_fallback(task, intent, max_fallbacks)`
- **`build_default_registry()`** — factory that pre-populates registry with all built-in agents

### Added — Nemotron Router (intelligent task dispatch)
- **`NemotronClassifier`** — sends task + agent list to Nemotron (Ollama `nemotron-mini`) for JSON classification; gracefully falls back to keyword scoring when Ollama is unavailable
- **`NemotronRouter`** — runs health checks → filters available agents → classifies via Nemotron → validates choice → builds fallback chain; `route_and_execute()` tries chain until success
- **`NemotronDispatch`** — high-level dispatcher with in-memory history (configurable limit) and aggregated stats (total, success_rate, agents_used, avg_duration_ms)
- **`RoutingDecision`** — captures classification result, selected agent, fallback chain, health_filtered flag, duration
- **`DispatchRecord`** — captures task preview, routing decision, agent result, total duration, timestamp
- **6 REST endpoints** at `/api/nemotron/`:
  - `POST /route` — classify + execute; returns output + routing metadata
  - `POST /classify` — classify only (no execution)
  - `GET /agents` — list all agents with health status
  - `GET /agents/{name}/health` — single-agent health
  - `GET /history` — recent dispatch records
  - `GET /stats` — aggregated dispatch statistics
- Registered in `server.py` alongside other route modules
- **43 + 22 = 65 tests** passing (`test_active_agents.py`, `test_nemotron.py`)

### Stats
- **+65 new tests** (total 1618 passing)
- **+2 new Python packages** (`active_agents`, `nemotron`)
- **+6 new REST endpoints** at `/api/nemotron/`
- Full Orchestra → Nemotron → Active Agent pipeline complete

---

## [0.1.0] — 2026-04-07

### Added — Core Orchestration
- **Five architectures (A–E)**: Monolithic, RAG Pipeline, Agent Swarm, MCP Tool Hub, Production Stack
- **Kimi K2.5** as primary backbone model via Moonshot AI API
- **Adaptive context** — 262K token window, auto-compresses at 80% capacity
- **Long-horizon tasks** — checkpoint/resume for multi-hour workflows (up to 4h)
- **Token streaming** — SSE + WebSocket real-time output
- **Model router** — intelligent dispatch across Kimi K2.5, Claude, GPT, Gemini

### Added — MILES Personal AI
- Intelligence, voice, awareness, routines modules
- Persistent cross-session memory with semantic search
- Daily briefings, scheduled routines, context awareness

### Added — Frontier Browser
- Non-blocking sandbox-first browser (like Perplexity Comet)
- DOM interpreter — transforms DOM into typed callable/assignable objects
- Shared context store across all agents (thread-safe, namespaced by tab)
- Up to 10 concurrent isolated sandboxes
- Dual-channel event streaming (SSE + WebSocket)
- Prompt injection defense, URL blocking, approval workflow

### Added — Cloud Infrastructure
- **AWS Lambda** runtime with SAM/CDK IaC
- **Terafab** custom infrastructure runtime
- **GPU provider registry** — 7 providers (CoreWeave, Lambda, AWS, GCP, OCI, RunPod, Spheron)
- **GPU specs** — 10 types including GB200 NVL72, B200, H200, H100
- **GPU cluster management** — multi-node, tensor/pipeline parallel, NVLink topology
- **Autoscaler** — cost-optimized cross-provider scaling, spot instance support
- **Inference router** — 6 routing strategies, model-GPU affinity, failover
- **WebSocket relay**, cloud files (S3), session persistence (DynamoDB)

### Added — OS-Level Sandbox Hardening
- Debian 11 (59,913 packages), Fedora 37 (66,166), OpenBSD 7.3 (7,787), FreeBSD 13.2 (30,766)
- Linux namespace isolation (PID, NET, MNT, USER, UTS, IPC)
- cgroup v2 resource limits
- Seccomp-BPF with 368-entry x86_64 syscall table
- OverlayFS, tmpfs, path masking, minimal /dev
- 4 isolation levels: minimal, standard, maximum, paranoid
- OpenBSD pledge/unveil, FreeBSD capsicum/jail support

### Added — Billing
- Stripe integration with 4 tiers: Free/$0, Pro/$20, Team/$25/seat, Max/$250
- Architecture-aware feature gating (Free→A only, Max→all)
- Per-architecture limits (tool calls, tokens, sub-agents, sources, concurrent tasks)
- Cost estimation with component breakdown before execution
- Billing middleware wrapping all architectures

### Added — Finance Terminal
- 25 tools across 7 modules
- Real-time quotes, historical data, options chains
- Portfolio analysis, risk metrics, earnings calendar
- Macro indicators, cryptocurrency, FX

### Added — Security
- Adversarial filter, DDoS protection, WAF
- Red-team grade hardening
- Trust boundary system

### Added — Multi-Language Stack
- **Go** (`go/envd/`) — Sandbox manager, gRPC server, Firecracker microVM
- **Rust** (`rust/orchestra-core/`) — BPE tokenizer, HNSW index, seccomp-BPF compiler
- **TypeScript SDK** (`sdk/`) — Type-safe client for all 29 API routes
- **Node.js backend** (`node/`) — Express bridge, WebSocket relay, SSE, Zod validation
- **Shell scripts** (`scripts/`) — Bootstrap, health check, deploy, backup

### Added — Media Pipeline
- ffmpeg wrapper (convert, trim, merge, thumbnails, subtitles)
- yt-dlp wrapper (download video/audio, extract info)
- Image generation (DALL-E 3, FLUX, Stable Diffusion)
- Video generation (Veo, Sora, Runway)
- TTS (OpenAI, ElevenLabs)
- STT / Whisper (transcription, translation, SRT/VTT)
- Image processing (Pillow/ImageMagick)

### Added — Document Factory
- PDF (WeasyPrint → ReportLab fallback)
- PPTX with 7 slide layouts (python-pptx)
- XLSX with charts and formatting (openpyxl)
- Charts and visualizations (matplotlib → plotly)
- Document conversion via Pandoc with Python fallbacks

### Added — Embeddings Service
- 6 embedding models (OpenAI text-embedding-3, Voyage, Nomic, BGE)
- HNSW in-memory vector index
- pgvector PostgreSQL integration (IVFFlat + HNSW indexes)
- 5 chunking strategies (fixed, sentence, paragraph, semantic, recursive)
- End-to-end embedding pipeline (ingest → chunk → embed → store → search)

### Added — Mobile PWA
- Installable PWA (manifest, service worker, offline queue)
- Touch-optimized chat UI (swipe gestures, bottom nav, voice input)
- Push notifications (VAPID, APNs/FCM, iOS Safari compat)
- Offline queue with IndexedDB (50MB, LRU eviction, exponential backoff retry)

### Added — 16 Connectors
Gmail, GitHub, Slack, Notion, Linear, Snowflake, Google Calendar, Google Drive,
Jira, HubSpot, Airtable, Stripe, AWS, Monday, MCP bridge, base

### Added — API
- 29 REST routes (FastAPI production server)
- JSON Schema definitions for all request/response types
- 35 error codes with standard envelope format
- Full TypeScript SDK

### Added — Infrastructure
- `pyproject.toml` with 8 extras groups
- Multi-stage Dockerfile + docker-compose (Postgres + Redis)
- GitHub Actions CI: lint, typecheck, test (Python 3.11 + 3.12), Docker build
- `horizon` CLI: `run`, `serve`, `status`, `validate`

### Stats
- 165 Python modules, 79,597 lines
- 5 TypeScript files (SDK), 10 TypeScript files (Node)
- 5 Go files, 5 Rust files, 5 Shell scripts
- **87,960 total lines across 6 languages**
- **268 tests passing**
