## Goal
- Build a full-stack autonomous AI agent platform with multi-channel ingestion, layered context management, defense-in-depth security, K8s deployment, CLI, multi-language finance/logistics engines, brand websites, and Chromium (Horizon Frontier) build orchestration

## Constraints & Preferences
- All tests pass across all modules
- Backward-compatible imports preserved
- TypeScript for multi-channel message ingestion and finance orchestration; Python for agent core, finance engine, logistics engines, build orchestrator, gateway, and CI/CD scripts
- Defense-in-depth: gateway control plane, 4 security layers, model never first boundary
- Helm chart for K8s deployment with HPA, Ollama sidecar, ingress
- Deny-by-default across network, filesystem, process, and inference layers
- Finance: double-entry ledger, Excel + AI-native formula DSL, Monte Carlo simulation, CFO copilot
- Logistics v1: fleet management, route optimization, supply chain tracking, AI anomaly detection
- Logistics v2 (battle-ready): VRP/TSP heuristic + OR-Tools solver, ensemble demand forecasting, dynamic pricing, load matching, multi-agent dispatch, GPS telemetry pipeline, Temporal-style workflow engine, gRPC service layer
- Build Orchestrator: GN profile manager, build lifecycle, patch management, AI error analysis for Chromium builds

## Progress
### Done
- **vLLM provider**: VLLMProvider(BaseProvider) wrapping AsyncLLM with 4 presets, registered in ProviderFactory + ModelRegistry + ProviderDetector. Lazy import inside methods — no crash when vllm not installed.
- **Bug fixes**: SkillTool JSON-Schema → flat param format (fixed 'str' object has no attribute 'get'). ChatRequest moved to module level (fixed 422 on POST). httpx.AsyncClient(timeout=600) → httpx.Timeout(600, connect=10, pool=None) (fixed Windows hang). Model name .lower() normalization everywhere (fixed 404 "Nemotron not found").
- **UI redesign** (html.py): JARVIS mode toggle with gradient accent, Web Speech API mic button, image upload/paste, TTS for responses, responsive CSS (5 breakpoints down to 375px), glassmorphism header, custom scrollbars, toast notification system, iOS safe-area insets, PWA manifest + service worker.
- **Language scaffolding**: scaffold/context.py (LanguageDetector + LANGUAGE_CONTEXTS), rust.py (Cargo + clap + tokio + CI), typescript.py (lib/CLI/Next.js 3 variants), mojo.py (modules + Makefile + notebook). 10 total templates registered. 40 dedicated scaffold tests.
- **Observability stack**: Prometheus metrics (llm_calls_total, llm_tokens_total, tool_calls_total, llm.cost_usd, cache.access, session.cost_usd), LangFuse generation tracing, OTel exporter (metrics/traces/logs via OTLP), live dashboard at /observability, health endpoint with memory/GPU/providers. OTEL_ENABLED env var config.
- **Conversation memory**: _prior_messages preserved across _build_context() calls. session.messages now saves full agent.messages (system + all turns). PlanAndExecute.reason() includes context[-4:] (was silently ignoring). Session export at GET /api/sessions/{id}/export?fmt=md.
- **Layered context**: LayeredContext with 4 layers (prompt, evidence, reasoning, working memory) each with token budget envelopes. RetrievalPipeline (web + vector + knowledge base multi-source search, filter, rerank, summarize). WorkingMemory with extractive summarization of old turns.
- **Gateway + AgentRuntime**: Gateway (single entry point, API key auth, channel normalization). AgentRuntime (10-phase AI loop with pluggable on() hooks: ingest → auth → route → resolve → context → invoke → intercept → format → deliver → persist). PolicyEngine (allow/deny/require-sandbox per tool, rate limiting). SkillsRegistry (markdown/YAML playbooks from .agent-skills/). WebhookManager (HMAC verification, handler registry).
- **Frontier + Prince**: FrontierEngine with tab awareness, cross-tab summarization, Chromium-powered research_browser(). ContentScreener (layered defense, unsafe states trigger controlled stop). ConnectorRegistry + OAuthConnector (Google/Microsoft/GitHub OAuth 2.0 flows). PrinceSecurity (admin allowlist + user authorization dual gate).
- **Human-in-the-loop**: StepTracker with auto git commit on every major action (write/edit/scaffold/git). ApprovalManager (review/approve/reject/revert). HumanInTheLoopAgent wrapping the agent with step tracking and approval workflow.
- **Spaces + Artifacts**: SpaceManager (group chats by project, persist as JSON). ArtifactManager (generated outputs: charts, files, reports, code, images, maps). Right panel tabs for Context/Artifacts.
- **Multi-channel ingestion (TypeScript)**: channels/ts/ Express server on port 4500. 6 adapters: Slack, Telegram, WhatsApp (WebSocket + QR auth via whatsapp-web.js), Discord, iMessage (macOS), Email (nodemailer + IMAP). InboundMessage normalization with image validation. Python bridge at /api/channels/{channel} proxies to TS server.
- **Defense-in-depth security**: SecurityGateway (hub-and-spoke, authenticate before runtime, AccessLevel: DENY/RESTRICTED/STANDARD/ELEVATED). 4 layers: NetworkLayer (domain allowlist/denylist), FilesystemLayer (workspace confinement, secret scanning on write), ProcessLayer (command allowlist), InferenceLayer (injection shield + model policy). ChannelAuth (bot tokens, allowlists, DM pairing, mention gating). EgressController (deny-by-default outbound, rate-limited, auto-approved domains for OpenAI/Anthropic/GitHub/npm/PyPI).
- **REST API** (Express + C# .NET 8): POST /search/indexes/{name}/query with OData filter + facets + conversation history. CRUD /indexes with Edm schema system. GET /accounts/{id} for RAG grounding. POST /accounts/{id}/orders for action endpoints. GET /actions for schema discovery. x-trace-id header on every response.
- **GRC loop**: GRCLoop (generate → review → correct autonomous loop with max 5 iterations). TestRunner (pytest/cargo test/npm test output parsing, failure detection). ReviewTool (code review for TODOs, debug prints, secrets, long lines). Registered as "review" tool.
- **CLI** (cli.py): 9 new commands — chat (interactive with streaming), session list/show/delete/export, config show/set/init, completion bash|zsh|fish|powershell, version. Table-formatted output, --json flag for machine-readable.
- **Architecture navigation**: CapabilityRegistry (8 registered capabilities, format_for_prompt injected into agent context). IntentRouter (10 route definitions, pattern matching, suggest_workflow() returns 5-step tool sequence). ProjectNavigator (summarize project structure, file types, line counts).
- **Docker sandbox**: SandboxManager (lifecycle: create/exec/stop/cleanup, resource limits 512m/1 CPU/100 pids, read-only root, network isolated). SandboxExecuteTool registered as "sandbox_exec" with Python/Node/shell support. Files persist across calls in same session.
- **Helm chart**: charts/orchestra/ — full K8s deployment with HPA (2-10 pods, CPU > 70% or memory > 80%), Ollama sidecar (50Gi PVC for models), ingress with TLS, PDB (minAvailable: 1), ConfigMap env injection, RBAC service account, liveness/readiness/startup probes. Values override via --set or custom values.yaml.
- **Agent efficiency**: CPU mode returns thinking directly (no main loop). GPU mode auto-detects via nvidia-smi (not torch.cuda, avoids 1-3s import). keep_alive: "-1m" on Ollama requests (model stays loaded). System prompts trimmed 75%.
- **API Gateway** (api_gateway/): Production middleware stack — Token bucket rate limiter (10/s global, 60/min per IP, 300/min per user, 30/min per endpoint), JWT (HS256) + API key (SHA256-hashed) auth, Content-Type/body-size validation, trace ID logging. 31 tests. Endpoints: /health, /api/chat, /auth/token, /auth/api-key, /admin/gateway/stats, /admin/gateway/routes.
- **Service Discovery** (service_discovery/): ServiceRegistry (register/deregister/heartbeat/evict), DNSResolver (k8s suffix stripping, SRV/TXT records, local overrides), LoadBalancer (ROUND_ROBIN/RANDOM/WEIGHTED/PRIORITY/LEAST_CONNECTIONS), HealthChecker (HTTP + TCP + custom periodic checks), ServiceDiscoveryClient (high-level with call()/call_all() HTTP routing). 50 tests. FastAPI middleware auto-registers /sd/health, /sd/info, /sd/services, /sd/resolve/{name}, /sd/srv/{name}.
- **CI/CD Pipeline** (ci-cd/): Jenkinsfile — declarative pipeline (K8s pod agent, parallel build/test/lint, Docker build on main, staging auto/production manual). .gitlab-ci.yml — multi-stage with caching, artifacts, environments, DinD. ArgoCD — 3 Applications (main+staging+production), AppProject with RBAC, Kustomize overlay (deployment/service/ingress/HPA/configmap). Docker multi-stage build. Makefile with make ci full pipeline. 34 tests.
- **Jaeger Tracing** (tracing/): JaegerTracer — span creation/parenting/export, find_traces() by service/operation/tags, get_trace_detail(), stats. TracingMiddleware — auto-traces FastAPI HTTP, injects x-trace-id + traceparent. instrument_httpx() — patches AsyncClient.send for outgoing trace propagation. @trace_llm_call() — detailed LLM spans with model/latency/tokens. TracePropagator — W3C traceparent/tracestate inject/extract. AgentTracerBridge — bidirectional sync between file-based AgentTracer and OTel/Jaeger. tracing/tempo/ — Docker Compose (Tempo + Jaeger + Jaeger Collector + Grafana + OTel Collector). 40 tests.
- **Orchestra Create brand** (/create): Full design website — hero (gradient orbs, animated badge), 6 feature cards, 4-step workflow, 6 template grids, 3 testimonials, pricing CTA modal.
- **Orchestra Finance** (/finance + /finance/app): Brand page + 3-tab dashboard. src/code_agent/finance/ — FormulaEngine (DSL parser, 15 standard + 4 AI-native functions, dependency graph, incremental recalc), TransactionEngine (double-entry ledger, balance validation, trial balance, financial statements, DuckDB HTAP queries, reconciliation), AnalyticsEngine (TimeSeriesForecast exponential/linear/seasonal/MonteCarlo/VaR, what-if scenarios, risk analysis), FinanceBrain (AI formula registration, insight generation by severity, LLM CFO copilot), EventBus (Kafka-style topic pub/sub, replay, wildcard). 18 REST endpoints at /api/finance/. TypeScript orchestrator (channels/ts/src/finance/orchestrator.ts) with formula caching, bulk eval, event dispatch. 65 tests.
- **Orchestra Logistics v1** (/logistics + /logistics/app): Brand page + 4-tab dashboard (Fleet/Resources/Supply Chain/AI). src/code_agent/logistics/ — FleetEngine (register/assign/release/nearest/metrics), RoutingEngine (create/optimize/ETA/carbon tracking), SupplyChainEngine (warehouses/inventory/shipments/tracking/success rates), LogisticsBrain (route optimization, demand forecast, anomaly detection, fleet health scoring A/B/C/D, LLM copilot). 15 REST endpoints at /api/logistics/. 49 tests.
- **Orchestra Logistics v2 (battle-ready)** (src/code_agent/logistics2/): Multi-language enterprise architecture. Python: VRPSolver (OR-Tools interface + heuristic, 2-opt TSP), DemandForecaster (ensemble exp/lin/seasonal with volatility), DynamicPricingEngine (rate calc, spot market, lane profitability, reefer/hazmat surcharges). Python: HTAPEngine (DuckDB OLTP/OLAP lane/shipment/capacity queries), WhatIfSimulator (fleet expansion simulation, rate elasticity), PlanningEngine (lane/capacity planning). Python: LoadMatcher (multi-factor scoring: proximity/compat/profit/deadhead), RateEngine (carrier comparison, lane benchmarking), AgentOrchestrator (4 dispatch agents: dispatcher/compliance/cost/exception), NLPAgent (8 intent patterns, entity extraction). Python (Go-style): EventIngester (concurrent GPS/ELD pipeline, batch processing, simulated GPS feed), EventStream (Kafka/Pulsar pub/sub with partitioning). Python (Temporal-style): WorkflowEngine (sequential steps, retry, cancel, progress tracking), PlanningWorkflows (week-end close, daily dispatch, contract compliance), GRPCService (protobuf-compatible: SolveVRP/OptimizeTSP/MatchLoads/ForecastDemand). TypeScript scaffold (channels/ts/src/logistics/): dispatch-dashboard, planning-grid, map-view. Go scaffold (go-services/telemetry/): main.go, ingester.go, kafka.go. 42 tests.
- **Build Orchestrator** (src/code_agent/build_orchestrator/): 73 tests — models (6 dataclasses + 4 enums), BuildProfileManager (20 built-in GN profiles including 3 Horizon Frontier presets), BuildEngine (build lifecycle create/simulate/cancel, ninja output parsing, time estimation, parallelism suggestions), PatchManager (8 predefined Horizon Frontier patches with apply/unapply/conflict detection), BuildBrain (error analysis with 7 known patterns, optimization suggestions, LLM copilot with offline fallback). 34 REST endpoints at /api/build/. Dashboard at /build/app with 5 tabs (Profiles/Builds/Patches/AI Brain/Metrics). Brand page at /build. Registered in server.py.
- **Documentation** (docs/): 9 comprehensive documents — architecture overview, API gateway, service discovery, tracing pipeline, CI/CD pipeline, finance engine, logistics v1, logistics v2, build orchestrator.
- **Git remote**: chromium → https://github.com/astewartfritz/Horizon-Frontier.git added
- **Horizon Frontier source**: Shallow cloned to C:\Users\ashto\hf-src (full Chromium tree)
- **depot_tools**: Installed at C:\Users\ashto\depot_tools, added to user PATH
- **gn & ninja**: Binary download via CIPD — gn.exe v2397 at depot_tools\gn\gn\windows-amd64, ninja.exe v1.13.2 from GitHub release
- **gclient**: Fixed missing httplib2==0.19.1 dependency (httplib2==0.31.2 removed socks module). .gclient file configured for hf-src with name='.' (root-level checkout)

### In Progress
- Building Horizon Frontier Chromium — gclient sync started as detached process (12:43 PM, PID 61216, 5 git subprocesses)

### Blocked
- Chromium compilation requires Visual Studio 2022 with "Desktop development with C++" workload + Windows SDK. Not present on this machine.

## Key Decisions
- TypeScript for channel adapters (WhatsApp WebSocket, Discord gateway, Telegram bot API all have native TypeScript SDKs) and finance/logistics orchestration
- Go template in Helm YAML fails PyYAML validation — expected, requires helm lint
- Security: deny-by-default across all 4 layers rather than allow-by-exception
- Device-specific: nvidia-smi subprocess for GPU detection (completes in <10ms without GPU, avoids torch import hang on CPU-only machine)
- Agentic loop disabled on CPU (single return), full tool loop auto-enables with GPU
- Finance formula engine: custom DSL parser with dependency graph + AI-native functions registered at runtime via register_ai_formula()
- Logistics VRP: OR-Tools for optimal solutions, heuristic (polar-angle clustering + nearest-neighbor TSP + 2-opt) as fallback when ortools not installed
- Build orchestrator: 20 pre-built GN profiles mirror official Chromium targets + 3 custom Horizon Frontier profiles; all WebUI toolbar features (kWebUILocationBar, kWebUIExtensionsContainer, etc.) are DISABLED_BY_DEFAULT in upstream Chromium
- Multi-language architecture: Python for AI/ML + orchestration engines, TypeScript for web UI + dispatch agents, Go for high-throughput telemetry ingestion

## Next Steps
- Wait for gclient sync to complete (downloads Chromium DEPS-defined third_party dependencies)
- Install Visual Studio 2022 + Windows SDK to enable Chromium compilation
- Run gn gen out/Default to generate ninja build files
- Use dashboard at http://localhost:8000/build/app to select Horizon Frontier profile and kick off the build
- Apply Horizon Frontier patches (8 predefined) from the Patches tab before building
- Explore Chromium's WebUI system for further customization (toolbar, NTP, themes)

## Critical Context
- 384+ tests pass across all modules (31 API gateway + 50 service discovery + 34 CI/CD + 40 tracing + 65 finance + 49 logistics v1 + 42 logistics v2 + 73 build orchestrator + inherited core/scaffold tests)
- Server persists via Windows Scheduled Task (schtasks /Run /TN "Orchestra" runs python run.py --host 0.0.0.0 --port 8000)
- TypeScript channels server runs on port 4500; Python bridge at /post/channels/{channel} proxies to it
- Finance API: /api/finance/ with 18 endpoints. Logistics API: /api/logistics/ with 15 endpoints. Build API: /api/build/ with 34 endpoints. Gateway admin: /api/gateway/*
- Brand pages: /create, /finance, /finance/app, /logistics, /logistics/app, /build, /build/app
- All engines (gateway, tracing, finance, logistics, build orchestrator) use in-memory state — restart loses data (no database dependency)
- Helm chart requires helm CLI to lint (PyYAML errors from Go template syntax are expected)
- Docker sandbox tool requires Docker installed and in PATH
- 10 project templates registered: rust, typescript 3, mojo, python 3, web, fastapi
- /api/health returns: status, version, memory, GPU, providers (Ollama model list, vLLM availability)
- Ollama servers auto-detected via /api/tags; vLLM auto-detected via import vllm
- Horizon Frontier source at C:\Users\ashto\hf-src (shallow clone, Chromium tip-of-tree)
- depot_tools at C:\Users\ashto\depot_tools — gn v2397, ninja v1.13.2 installed; gclient fixed (httplib2==0.19.1 installed, .gclient configured)
- gclient sync --with_branch_heads --no-history -j2 running as detached process since 12:43 PM (PID 61216)
- Chromium's WebUI toolbar features (kWebUILocationBar, kWebUIHomeButton, kWebUIBackForwardButton, kWebUIReloadButton, kWebUIBatterySaverButton, kWebUIAppMenuButton, kWebUISplitTabsButton, kWebUIPinnedToolbarActions, kWebUIExtensionsContainer, kRestrictedWebUICodeCache) all DISABLED_BY_DEFAULT in chrome/common/chrome_features.cc

## Relevant Files
- src/code_agent/api_gateway/: Gateway middleware stack (31 tests) — rate limiter, JWT+API key auth, validation, logging
- src/code_agent/service_discovery/: Service discovery (50 tests) — registry, DNS resolver, load balancer, health checker, FastAPI middleware
- src/code_agent/tracing/: Jaeger tracing (40 tests) — tracer, FastAPI/httpx/LLM instrumentation, W3C propagator, AgentTracer bridge
- tracing/tempo/: Docker Compose — Tempo + Jaeger + Grafana + OTel Collector
- ci-cd/: CI/CD pipeline (34 tests) — Jenkinsfile, .gitlab-ci.yml, ArgoCD Kustomize, Dockerfile, Makefile, build/test/lint/deploy scripts
- src/code_agent/finance/: Finance engine (65 tests) — formula.py, ledger.py, analytics.py, brain.py, events.py, routes.py
- channels/ts/src/finance/orchestrator.ts: TypeScript finance orchestrator with formula caching and event dispatch
- src/code_agent/logistics/: Logistics v1 (49 tests) — fleet.py, routing.py, supply_chain.py, brain.py, routes.py
- src/code_agent/logistics2/: Logistics v2 battle-ready (42 tests) — optimization/ (vrp, demand_forecast, dynamic_pricing), data/ (htap, what_if, planning), dispatch/ (load_matcher, rate_engine, agent_orchestrator, nlp_agent), telemetry/ (event_ingester, streaming), orchestration/ (workflow_engine, planning_workflows, grpc_service)
- channels/ts/src/logistics/: TypeScript logistics UI scaffold — dispatch-dashboard, planning-grid, map-view
- go-services/telemetry/: Go telemetry service scaffold — main.go, ingester.go, kafka.go
- src/code_agent/build_orchestrator/: Build orchestrator (73 tests) — models.py, profiles.py (20 GN profiles), engine.py (build lifecycle, output parsing), patches.py (8 HF patches), brain.py (AI analysis, LLM copilot), routes.py (34 endpoints)
- src/code_agent/ui/build_orchestrator/: Build UI — brand.py (landing page), dashboard.py (5-tab interactive dashboard)
- src/code_agent/ui/server.py: Routes for /build, /build/app + build orchestrator API registration
- docs/09-build-orchestrator.md: Full build orchestrator documentation
- src/code_agent/ui/create.py: Orchestra Create brand page HTML
- src/code_agent/ui/finance.py: Orchestra Finance brand + app HTML
- src/code_agent/ui/logistics.py: Orchestra Logistics brand + app HTML
- src/code_agent/ui/html.py: Complete UI (1516 lines) — JARVIS mode, voice/image/TTS, Spaces/Artifacts sidebar, responsive CSS, PWA
- src/code_agent/agentic/: GRC loop, TestRunner, ReviewTool, CapabilityRegistry, IntentRouter, ProjectNavigator
- src/code_agent/security/: Gateway, layers (network/filesystem/process/inference), channel_auth, egress controller
- src/code_agent/sandbox/: Manager (lifecycle), policy (resource limits), execute tool, DockerSandbox
- channels/ts/: TypeScript Express server (port 4500) with 6 channel adapters
- charts/orchestra/: Helm chart with deployment, HPA, ingress, PVC, Ollama sidecar, PDB
- C:\Users\ashto\hf-src: Shallow-cloned Chromium source (Horizon Frontier fork), 1.75M commits
- C:\Users\ashto\depot_tools: Installed depot_tools with gn v2397 and ninja v1.13.2

## New: LLM-as-Router Architecture (Multi-Agent Orchestration)
### Python (`src/code_agent/orchestrator/router/`)
- **RouterPlanner**: LLM-based master planner that decomposes user requests into step plans. Detects intent (8 types), builds plans with agent assignments, supports adaptive re-planning on failure. Falls back to intent-routing table when LLM unavailable.
- **AgentPool**: Per-model agent management with model binning (3B-8B quantized models per role). Builds role-tailored prompts with context injection and history formatting. 8 agent classes: coder, reasoner, summarizer, validator, scratch, searcher, extractor, planner.
- **StateGraph**: Global state graph with full trace logging. Create/update/complete/delete state lifecycle. Exportable traces for audit and replay. Per-step history with status tracking.
- **ResultAggregator**: Executes plans step-by-step with retry logic and fallback model routing. Builds final output by merging results (code merge, summary pass-through, step-by-step for reasoning). Calls fallback models on primary failure.
- **API**: 9 REST endpoints at `/api/router/` — plan, execute, detect, state, trace, states list, delete, agents, health. Registered in server.py.
- **Tests**: 34 tests covering all models, planner (intent detection, JSON extraction, fallback), agent pool (prompt building, model selection), state graph (CRUD, tracing, export), and integration flows.

### Rust (`rust/orchestra-core/src/router.rs`)
- **Router**: Fast intent classifier using keyword matching (microsecond latency, no LLM call). Routes to optimal agent chain per intent type.
- **ModelSelector**: Priority-based model selection with overrides. Maps agent class + task hint to best-fit model.
- **IntentClassifier**: Keyword-based intent detection for 5 categories (code, reasoning, summary, search, general). Runs inline, no network call.
- **PyO3 bindings**: PyRouter, PyIntentClassifier, PyModelSelector classes exposed to Python via `orchestra_core.router`.

### Go (`go-services/router/`)
- **State manager**: HTTP server on port 8400 with in-memory state store. 9 REST endpoints matching the Python state graph API.
- **Event streaming**: SSE endpoint at `/api/events` for real-time state change notifications. Pub/sub watcher pattern.
- **Thread-safe store**: RWMutex-guarded state with create/read/update/delete operations. Full trace event logging per task.
