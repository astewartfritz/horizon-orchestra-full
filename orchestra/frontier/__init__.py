"""Frontier — Horizon's non-blocking, sandbox-first browser.

Unlike traditional browser automation that blocks the UI, Frontier runs
every agent task in an isolated sandbox while the user continues working.
Multiple agents share a DOM interpreter and context store but execute
independently.

Architecture::

    ┌──────────────────────────────────────────────────────┐
    │  User's Browsing Session (never blocked)             │
    │  ┌──────────────┐  ┌──────────────┐                  │
    │  │ Active Tab 1  │  │ Active Tab 2  │  ...            │
    │  └──────────────┘  └──────────────┘                  │
    └──────────────┬───────────────────────────────────────┘
                   │ shared read
    ┌──────────────▼───────────────────────────────────────┐
    │  Context Store (thread-safe, namespaced)              │
    │  DOM snapshots • extracted data • cookies • memory    │
    └──────────────┬───────────────────────────────────────┘
                   │ read/write
    ┌──────────────▼───────────────────────────────────────┐
    │  Sandbox Pool (up to 10 concurrent)                   │
    │  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
    │  │ Sandbox 1 │  │ Sandbox 2 │  │ Sandbox 3 │  ...    │
    │  │ Agent ←→  │  │ Agent ←→  │  │ Agent ←→  │         │
    │  │ Bridge    │  │ Bridge    │  │ Bridge    │         │
    │  └──────────┘  └──────────┘  └──────────┘           │
    └──────────────────────────────────────────────────────┘

Core layer:
  - :mod:`dom_interpreter` — typed DOM objects, accessibility tree
  - :mod:`context_store` — shared state across all agents
  - :mod:`sandbox` — isolated browser execution environments

Runtime layer:
  - :mod:`task_runner` — non-blocking task orchestration, dual-channel events
  - :mod:`agent_bridge` — RPC dispatch (LLM → browser actions)
  - :mod:`safety` — hard boundaries, prompt injection defense, approval flow
"""

from .dom_interpreter import (
    DOMInterpreter,
    DOMSnapshot,
    DOMNode,
    DOMAction,
    InteractableElement,
    FormGroup,
    InterpreterConfig,
)
from .context_store import (
    ContextStore,
    ContextStoreConfig,
    ContextEntry,
    PageContext,
)
from .sandbox import (
    BrowserSandbox,
    SandboxPool,
    SandboxConfig,
    SandboxState,
    SandboxMetrics,
)
from .task_runner import (
    FrontierTaskRunner,
    FrontierTask,
    TaskEvent,
    TaskRunnerConfig,
)
from .agent_bridge import (
    AgentBridge,
    BrowserCommand,
    CommandResult,
    LLMActionPlanner,
)
from .safety import (
    FrontierSafetyGuard,
    SafetyConfig,
    ApprovalRequest,
)

__all__ = [
    # Core — DOM
    "DOMInterpreter",
    "DOMSnapshot",
    "DOMNode",
    "DOMAction",
    "InteractableElement",
    "FormGroup",
    "InterpreterConfig",
    # Core — Context
    "ContextStore",
    "ContextStoreConfig",
    "ContextEntry",
    "PageContext",
    # Core — Sandbox
    "BrowserSandbox",
    "SandboxPool",
    "SandboxConfig",
    "SandboxState",
    "SandboxMetrics",
    # Runtime — Task Runner
    "FrontierTaskRunner",
    "FrontierTask",
    "TaskEvent",
    "TaskRunnerConfig",
    # Runtime — Agent Bridge
    "AgentBridge",
    "BrowserCommand",
    "CommandResult",
    "LLMActionPlanner",
    # Runtime — Safety
    "FrontierSafetyGuard",
    "SafetyConfig",
    "ApprovalRequest",
]
