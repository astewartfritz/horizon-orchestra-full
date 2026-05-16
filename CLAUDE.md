# Code Agent — Architecture & Design Philosophy

This document explains why this project is structured the way it is. Use it as your mental model when building, extending, or debugging.

---

## Core Insight

An AI coding agent is **not a single model call**. It is a **feedback loop**:

```
User Task
  → LLM plans → executes tools → observes results → plans again
  → LLM reflects → refines → repeats
  → Produces final output
```

Everything in this project exists to make that loop **reliable, observable, extensible, and efficient**.

---

## Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    CLI / API / TUI / REPL               │  Interfaces
├─────────────────────────────────────────────────────────┤
│                    Agent Loop (agent.py)                 │  Core
├──────────────────────┬──────────────────────────────────┤
│   Tool System (31)   │  LLM Abstraction (multi-provider)│  Engine
├──────────────────────┴──────────────────────────────────┤
│  Memory · Cache · Sessions · Context · Rate Limit       │  Infrastructure
├─────────────────────────────────────────────────────────┤
│  Knowledge · Vector · Analysis · Quality · Security     │  Intelligence
├─────────────────────────────────────────────────────────┤
│  Multi-Agent · Swarm · Pipeline · Workflow · Scheduler  │  Orchestration
├─────────────────────────────────────────────────────────┤
│  Export · Telemetry · Logs · Monitor · Dashboard        │  Observability
├─────────────────────────────────────────────────────────┤
│  Profiles · Templates · Prompts · PromptVersion         │  Configuration
├─────────────────────────────────────────────────────────┤
│  Code Transform · Smells · Health · Validate · Diagnose │  Quality
├─────────────────────────────────────────────────────────┤
│  Notify · GitHub · MCP · Plugins · Market               │  Integration
└─────────────────────────────────────────────────────────┘
```

---

## Why 77 CLI Commands?

Every command maps to a **single capability** an agent or user might need:

| Category | Commands | Why |
|----------|----------|-----|
| **Run** | `run`, `repl`, `tui`, `serve`, `daemon`, `apiserver` | Multiple interaction modes for different workflows |
| **Read/Write** | `read`, `write`, `edit`, `glob`, `grep`, `sql`, `api` | The agent needs to inspect and modify code |
| **Analyze** | `analyze`, `multilang`, `vector`, `smells`, `quality`, `deps`, `licenses` | Understand code before changing it |
| **Verify** | `review`, `audit`, `validate`, `health`, `diagnose`, `testgen`, `testwatch` | Ensure correctness and safety |
| **Improve** | `improve`, `transform`, `refactor`, `optimize`, `errors` | Auto-fix and auto-enhance |
| **Knowledge** | `knowledge`, `memsearch`, `sessearch`, `context` | Remember past work |
| **Orchestrate** | `swarm`, `workflow`, `pipeline`, `schedule`, `batch`, `abtest` | Coordinate complex multi-step work |
| **Observe** | `logs`, `traces`, `cost`, `monitor`, `dashboard`, `estimate` | See what's happening |
| **Configure** | `init`, `profile`, `template`, `prompt`, `promptver`, `completions` | Customize behavior |
| **Share** | `notify`, `export`, `hooks`, `github`, `mcp`, `market`, `plugins` | Integrate with the world |
| **Visualize** | `graphviz`, `docgen`, `image`, `arch` | Make things visible |
| **Collaborate** | `collab`, `swarm`, `human`, `reviews` | Team up with agents and humans |

**Design rule**: If a capability is useful enough to be a library function, it deserves a CLI command. No hidden power.

---

## Why 31 Tools?

Tools are the **agent's hands**. They map one-to-one to actions an AI can take:

- **File tools** (`read`, `write`, `edit`, `glob`): The agent reads and writes code
- **Search tools** (`grep`, `index`, `analyze`): The agent finds what it needs
- **Execution tools** (`bash`, `sandbox`, `sql`, `api`, `jupyter`): The agent runs things
- **Code tools** (`diff`, `patch`, `apply_edit`, `transform`, `testgen`): The agent modifies code surgically
- **Web tools** (`webfetch`, `websearch`): The agent researches
- **Git tools** (`git`): The agent versions
- **Meta tools** (`task`, `scaffold`, `docgen`, `graphviz`, `watch`): The agent delegates
- **Intelligence tools** (`knowledge`, `security_audit`, `multilang`, `swarm`, `improve`, `workflow`): The agent uses higher-order reasoning

**Design rule**: Every tool must be independently testable, have a clear spec, and return `ToolResult`.

---

## Why 88 Source Modules?

Each module has exactly **one responsibility**:

| Pattern | Example | Reason |
|---------|---------|--------|
| `foo/base.py` | `knowledge/base.py` | Core implementation, framework-agnostic |
| `foo/tool.py` | `knowledge/tool.py` | Tool wrapper for the agent to call |
| `foo/__init__.py` | `knowledge/__init__.py` | Clean public API surface |
| `foo/manager.py` | `profiles/base.py` | State management for config-like things |
| `foo/scanner.py` | `security/scanner.py` | Stateless analysis utilities |
| `foo/engine.py` | `pipeline/engine.py` | Multi-step process coordination |

**Design rule**: A module should fit in your head. If you need to scroll to understand it, split it.

---

## Key Design Decisions

### 1. `get_all_tools()` is lazy
```python
# tools/__init__.py
def get_all_tools() -> list[type[Tool]]:
    extra = []
    try:
        from code_agent.knowledge.tool import KnowledgeTool
        extra.append(KnowledgeTool)
    except ImportError:
        pass  # graceful degradation
    return CORE_TOOLS + extra
```
**Why**: Circular imports are the #1 killer of Python agent frameworks. Lazy loading means every tool can import anything from `code_agent.*` without worrying about import order.

### 2. Every module has `__init__.py` that re-exports
```python
# memory/__init__.py
from code_agent.memory.base import NullMemory, JSONMemory, SQLiteMemory
__all__ = ["NullMemory", "JSONMemory", "SQLiteMemory"]
```
**Why**: Users (and the agent) should `from code_agent.memory import SQLiteMemory`, not dig into internal paths. Clean API = clean code.

### 3. Config is dataclasses, not dicts
```python
@dataclass
class AgentConfig:
    llm: LLMConfig = field(default_factory=LLMConfig)
    max_iterations: int = 50
```
**Why**: Type safety, IDE autocomplete, serialization. Dict-based configs hide bugs until runtime.

### 4. Tool results are structured
```python
@dataclass
class ToolResult:
    output: str = ""
    error: str = ""
    def __bool__(self): return not self.error
```
**Why**: The agent needs to know if a tool succeeded. String-based returns are ambiguous. `if result:` is unambiguous.

### 5. All persistence is file-based
- Sessions → `.code-agent-sessions/`
- Knowledge → `.code-agent-knowledge.db`
- Logs → `.agent-logs/`
- Profiles → `.agent-profiles/`
- Traces → `.agent-traces.jsonl`

**Why**: Zero infrastructure. No databases to install, no services to configure. `pip install` and go.

---

## How to Extend

### Add a new tool:
1. Create `src/code_agent/foo/tool.py` with a class extending `Tool`
2. Add the import to `tools/__init__.py`'s `get_all_tools()`
3. Add a CLI command in `cli.py` (optional)
4. Done. No config files to edit.

### Add a new module:
1. Create `src/code_agent/foo/__init__.py`
2. Implement in `src/code_agent/foo/base.py`
3. Export from `__init__.py`
4. Add to `code_agent/__init__.py` exports

### Add a new CLI command:
1. Add a `@main.command()` function in `cli.py`
2. Import your module lazily inside the function
3. Done. Click auto-discovers it.

---

## Why This Matters

Most AI coding tools are **black boxes**: send a prompt, get an answer, trust the result.

This project is the **opposite**:
- Every tool call is logged → `code-agent logs`
- Every dollar spent is tracked → `code-agent cost`
- Every reasoning step can be traced → `code-agent traces`
- Every session is searchable → `code-agent sessearch`
- Every error is categorized → `code-agent errors`
- Everything can be exported → `code-agent export`

**You can audit, debug, and improve every decision the agent makes.**

That's the point. Build with confidence.
