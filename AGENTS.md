# Agent Instructions — Horizon Orchestra

## Project Structure

```
orchestra/              # Legacy package (installed via pip install -e .)
  __init__.py           # Re-exports all public API — add new exports here
  guardian/             # Security middleware (CodeGuard, IngestionGate, PolicyEngine, etc.)
  teams/                # Team primitives (OrchestraTeam, OrchestraFleet, AgentNegotiator, OrchestratorMesh)
  tasks/                # Task manager, IPC, scheduling
  citation/             # Citation tracking and grounding
  skills/               # Skill system (parsing, loading, registry, activation)
  model_council/        # Multi-model deliberation

src/code_agent/         # New modules
  agentmesh/            # P2P agent mesh (registry, node, network, router, protocol, routes)
  teams/                # Team formation + swarm (formation, team, swarm, routes)
  channels/             # Channels v2 additions (health, formatter, retry, queue, gateway_routes)
  workflow_v2/          # DAG Workflow Engine v2 + REST routes
  reasoning/            # Reasoning strategies + REST routes (/api/reasoning/)
  monitor/              # Metrics + alerting + REST routes (/api/monitor/)
  telemetry/            # Agent tracing + REST routes (/api/telemetry/)

orchestra_science/      # AI-for-science subsystem (separate pip-installable package)
  ingestion/            # PubChem, RDKit, BioPython, PyMOL data ingestion
  analysis/             # Cheminformatics, bioinformatics, scientific visualization
  workflows/            # Molecular docking + literature review DAG pipelines
  reporting/            # Lab report, research paper, protocol generation
  server/               # FastAPI router at /api/science/* (register_science_routes)
  integration/          # ScienceAdapter bridges to main orchestra

knowledge/              # Hardware architecture plans
  horizon-orion.md      # Horizon Orion — custom LLM silicon specifications

tests/                  # All tests
  test_orchestra_science/  # 37 tests for the science subsystem
```

## Hardware Knowledge

The `knowledge/` directory contains architectural specifications for Horizon Orion chips — custom parallel compute devices optimized for LLM inference/training. When asked about hardware, silicon, chips, or the Orion project, read `knowledge/horizon-orion.md` first. The mission is to design and fabricate custom silicon that minimizes data movement per token using dataflow architectures.

## Conventions

### Testing
- Run: `python -m pytest tests/<file>.py -v --tb=short`
- **Always use `--cache-clear`** to avoid stale `.pyc` issues
- Asyncio mode: `Mode.STRICT` (pytest-asyncio)
- Test files use `unittest.TestCase`-style classes with `test_` prefix methods
- Some sync tests wrap async calls via `asyncio.get_event_loop().run_until_complete(coro)`

### Code Style
- Python 3.13+ (also tested on 3.11–3.12)
- Type hints on all public functions and dataclass fields
- Imports: stdlib → third-party → local (alphabetical within groups)
- `__all__` in every `__init__.py` to control public API surface
- `try/except ImportError` for optional dependency imports (prevents import crashes)

### Export Pattern
All public classes must be exported from `orchestra/__init__.py` in both:
1. The top-level import block (under a `# ── Section ──` comment)
2. The `__all__` list

If the module has optional deps, wrap the import in `try/except ImportError: pass`.
Guardian and teams exports are always wrapped in `try/except ImportError`.

### Version
- `orchestra/__init__.py` has `__version__` — keep in sync with `pyproject.toml`
- Current: `0.8.0`

### Git
- Branch: `feature/structured-thinking`
- Remote: `full` (primary push target)
- Commit messages: concise, imperative mood, describe the change

## Dual-Package Note
The project has two overlapping package roots:
- `orchestra/` (legacy, installed editable)
- `src/code_agent/` (new modules)

Many test imports reference `orchestra` but classes have moved to `code_agent`; others reference `code_agent` for new modules. Eventual consolidation is expected.
