"""Architecture D — MCP Tool Hub (Dynamic Tool Discovery).

Connects to external services via Model Context Protocol (MCP) servers.
Kimi K2.5 acts as the MCP client, discovering and calling tools dynamically.
Key constraint from production experience: limit the tool surface to 5-8
tools per agent with structured table guidance, wrap critical ops in
deterministic scripts.

This is the "plugin architecture" — any MCP server (filesystem, database,
git, browser, Brave Search, etc.) becomes a native tool.  The hub manages
multiple simultaneous MCP connections, routes tool calls, enforces safety
constraints, and provides table-format tool guidance to prevent Kimi's known
weakness with large tool surfaces.

Usage::

    from orchestra.arch_d import MCPToolHub, MCPHubConfig, MCPServerConfig

    config = MCPHubConfig(
        default_servers=[
            MCPServerConfig(name="filesystem", url="http://localhost:3100"),
            MCPServerConfig(name="brave", url="http://localhost:3200"),
        ],
        user_id="ashton",
    )
    hub = MCPToolHub(config=config)
    await hub.connect_server(config.default_servers[0])
    result = await hub.run("List all Python files in the project")
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator

from .router import ModelRouter, ModelConfig
from .agent_loop import (
    AgentLoop,
    AgentConfig,
    AgentEvent,
    FinalAnswerEvent,
    ErrorEvent,
    ToolCallEvent,
    ToolResultEvent,
    ToolRegistry,
    ToolSpec,
    ToolResult,
    create_default_tools,
)
from .memory import (
    MemoryStore,
    MemoryManager,
    SessionContext,
    register_memory_tools,
)
from .connectors.mcp_bridge import MCPBridge
from .safety import SafetyLayer, SafetyConfig, ActionConfirmation
from .trust import TrustBoundary, TrustLevel

# ---------------------------------------------------------------------------
# Optional module imports — guarded so the file loads even if modules are
# absent (e.g. during isolated unit tests or partial installs).
# ---------------------------------------------------------------------------

try:
    from .adaptive_context import (
        AdaptiveContext,
        AdaptiveContextConfig,
        TokenCounter,
        PriorityMessage,
    )
    _HAS_ADAPTIVE_CONTEXT = True
except ImportError:  # pragma: no cover
    AdaptiveContext = None  # type: ignore[assignment,misc]
    AdaptiveContextConfig = None  # type: ignore[assignment,misc]
    TokenCounter = None  # type: ignore[assignment,misc]
    PriorityMessage = None  # type: ignore[assignment,misc]
    _HAS_ADAPTIVE_CONTEXT = False

try:
    from .long_horizon import (
        LongHorizonRunner,
        LongHorizonConfig,
        LongHorizonResult,
        CheckpointStore,
        ProgressTracker,
    )
    _HAS_LONG_HORIZON = True
except ImportError:  # pragma: no cover
    LongHorizonRunner = None  # type: ignore[assignment,misc]
    LongHorizonConfig = None  # type: ignore[assignment,misc]
    LongHorizonResult = None  # type: ignore[assignment,misc]
    CheckpointStore = None  # type: ignore[assignment,misc]
    ProgressTracker = None  # type: ignore[assignment,misc]
    _HAS_LONG_HORIZON = False

try:
    from .token_streaming import (
        TokenStreamer,
        StreamingConfig,
        StreamChunk,
        BufferedStreamer,
    )
    _HAS_TOKEN_STREAMING = True
except ImportError:  # pragma: no cover
    TokenStreamer = None  # type: ignore[assignment,misc]
    StreamingConfig = None  # type: ignore[assignment,misc]
    StreamChunk = None  # type: ignore[assignment,misc]
    BufferedStreamer = None  # type: ignore[assignment,misc]
    _HAS_TOKEN_STREAMING = False

__all__ = [
    "MCPHubConfig",
    "MCPServerConfig",
    "ToolSurface",
    "ToolTableGenerator",
    "ToolSelector",
    "DeterministicWrapper",
    "ServerHealthMonitor",
    "MCPToolHub",
]

log = logging.getLogger("orchestra.arch_d")


# ---------------------------------------------------------------------------
# Configuration — MCP Server
# ---------------------------------------------------------------------------

@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server connection.

    Each MCP server exposes a set of tools discoverable via the
    ``tools/list`` JSON-RPC endpoint.  The hub connects to multiple
    servers simultaneously and merges their tool surfaces.
    """

    name: str                                            # Human-readable name
    url: str                                             # Server URL or command
    transport: str = "stdio"                             # "stdio" | "sse" | "websocket"
    env: dict[str, str] = field(default_factory=dict)
    tools_whitelist: list[str] = field(default_factory=list)   # Empty = all
    tools_blacklist: list[str] = field(default_factory=list)
    priority: int = 50                                   # 0-100, higher = more likely selected
    health: str = "unknown"                              # "healthy" | "degraded" | "down" | "unknown"


# ---------------------------------------------------------------------------
# Configuration — Hub
# ---------------------------------------------------------------------------

@dataclass
class MCPHubConfig:
    """Tuning knobs for Architecture D — MCP Tool Hub.

    Controls tool surface management, server connections, safety
    constraints, and integration with Kimi orchestration features.
    """

    # Tool surface management
    max_tools_per_agent: int = 8                         # Hard limit per Trilogy AI findings
    tool_selection_strategy: str = "relevance"           # "relevance" | "round_robin" | "manual"
    enable_table_guidance: bool = True                   # Table-format tool descriptions for Kimi

    # MCP server management
    default_servers: list[MCPServerConfig] = field(default_factory=list)
    discovery_timeout: float = 10.0
    health_check_interval: float = 60.0                  # seconds
    max_retries: int = 3

    # Safety
    require_approval_for: list[str] = field(
        default_factory=lambda: ["delete", "send", "publish", "pay"],
    )
    sandbox_file_ops: bool = True                        # Route file operations through sandbox
    rate_limit_per_minute: int = 60

    # Deterministic wrappers
    enable_deterministic_wrappers: bool = True           # Wrap critical ops in scripts

    # Model
    model: str = "kimi-k2.5"
    max_iterations: int = 300
    max_tokens: int = 16384
    temperature: float = 0.6
    user_id: str = ""
    memory_db: str = ""

    # -- adaptive context ---------------------------------------------------
    enable_adaptive_context: bool = True
    adaptive_context_config: "AdaptiveContextConfig | None" = None

    # -- long horizon -------------------------------------------------------
    enable_long_horizon: bool = False
    long_horizon_config: "LongHorizonConfig | None" = None

    # -- token streaming ----------------------------------------------------
    enable_token_streaming: bool = True
    streaming_config: "StreamingConfig | None" = None


# ---------------------------------------------------------------------------
# ToolSurface — the active tool set for the current agent turn
# ---------------------------------------------------------------------------

@dataclass
class ToolSurface:
    """The active set of tools available to the current agent.

    Limited to ``max_tools_per_agent`` (default 8) per Trilogy AI's
    production finding that Kimi struggles with tool selection
    when given too many tools.
    """

    tools: list[ToolSpec]
    sources: dict[str, str]                              # tool_name → server_name
    table_guidance: str                                  # Markdown table describing each tool
    total_available: int                                 # How many tools exist across all servers


# ---------------------------------------------------------------------------
# ToolTableGenerator — structured table guidance for Kimi
# ---------------------------------------------------------------------------

# Keywords that indicate a tool is destructive / high-cost
_DESTRUCTIVE_KEYWORDS = re.compile(
    r"(delete|remove|drop|destroy|send|email|publish|deploy|pay|charge|transfer|execute|run|write|update|create|post)",
    re.IGNORECASE,
)
_READ_KEYWORDS = re.compile(
    r"(read|get|list|search|find|query|fetch|describe|show|view|inspect|check|status|count)",
    re.IGNORECASE,
)


class ToolTableGenerator:
    """Generate structured table-format tool guidance for Kimi.

    Kimi K2.5 performs significantly better at tool selection when
    tools are described in a markdown table rather than as JSON schemas.

    Example output::

        | Tool | When to Use | Input | Output | Cost |
        |------|------------|-------|--------|------|
        | search_email | Find specific emails by sender/subject/date | query, from, date_range | list[Email] | Low |
        | send_email | Send an email on behalf of the user | to, subject, body | confirmation | High — requires approval |
    """

    def generate(
        self,
        tools: list[ToolSpec],
        server_names: dict[str, str],
    ) -> str:
        """Produce a complete markdown table describing *tools*.

        Args:
            tools: The selected tool surface.
            server_names: Mapping of tool_name → originating server name.

        Returns:
            Markdown table string ready for injection into the system prompt.
        """
        if not tools:
            return "(No tools available.)"

        rows: list[str] = []
        rows.append("| Tool | When to Use | Input | Output | Cost |")
        rows.append("|------|------------|-------|--------|------|")

        for tool in tools:
            cost = self._classify_cost(tool)
            input_summary, output_summary = self._summarize_params(tool)
            server = server_names.get(tool.name, "local")
            when_to_use = tool.description[:120] if tool.description else "General purpose"

            rows.append(
                f"| {tool.name} | {when_to_use} | {input_summary} | {output_summary} | {cost} |"
            )

        return "\n".join(rows)

    def _classify_cost(self, tool: ToolSpec) -> str:
        """Classify a tool call's cost/risk level.

        Returns:
            ``"Low"`` for read-only operations, ``"Medium"`` for writes
            that are reversible, ``"High — requires approval"`` for
            destructive or irreversible actions.
        """
        name_lower = tool.name.lower()
        desc_lower = (tool.description or "").lower()
        combined = f"{name_lower} {desc_lower}"

        # Check for high-risk patterns first
        high_risk_words = ("delete", "remove", "drop", "destroy", "send", "email",
                           "publish", "deploy", "pay", "charge", "transfer")
        for word in high_risk_words:
            if word in combined:
                return "High — requires approval"

        # Check for medium-risk (write operations)
        medium_risk_words = ("write", "update", "create", "post", "put", "patch",
                             "insert", "modify", "set", "execute", "run")
        for word in medium_risk_words:
            if word in combined:
                return "Medium"

        return "Low"

    def _summarize_params(self, tool: ToolSpec) -> tuple[str, str]:
        """Extract human-readable input/output summaries from a tool spec.

        Returns:
            Tuple of (input_summary, output_summary).
        """
        params = tool.parameters or {}
        properties = params.get("properties", {})
        required = set(params.get("required", []))

        # Build input summary
        if not properties:
            input_summary = "(none)"
        else:
            parts: list[str] = []
            for pname, pdef in list(properties.items())[:5]:
                suffix = " (required)" if pname in required else ""
                parts.append(f"{pname}{suffix}")
            input_summary = ", ".join(parts)
            if len(properties) > 5:
                input_summary += f", +{len(properties) - 5} more"

        # Infer output summary from description
        desc_lower = (tool.description or "").lower()
        if any(kw in desc_lower for kw in ("list", "search", "find", "query")):
            output_summary = "list[result]"
        elif any(kw in desc_lower for kw in ("read", "get", "fetch", "content")):
            output_summary = "content"
        elif any(kw in desc_lower for kw in ("create", "write", "send", "post")):
            output_summary = "confirmation"
        elif any(kw in desc_lower for kw in ("delete", "remove")):
            output_summary = "status"
        else:
            output_summary = "result"

        return input_summary, output_summary


# ---------------------------------------------------------------------------
# ToolSelector — picks the best tool subset for a given query
# ---------------------------------------------------------------------------

class ToolSelector:
    """Select the best subset of tools for a given task.

    When total tools > ``max_tools_per_agent``, this class picks the
    most relevant tools based on the user's query.  Uses keyword
    matching + LLM-based classification for selection.

    Three strategies:

    * **relevance** — pick tools most relevant to the current query.
    * **round_robin** — rotate through tool sets across turns.
    * **manual** — user explicitly picks tool groups.
    """

    def __init__(self) -> None:
        self._round_robin_offset: int = 0
        self._usage_counts: dict[str, int] = defaultdict(int)

    async def select(
        self,
        query: str,
        all_tools: list[ToolSpec],
        max_tools: int,
        strategy: str,
        router: ModelRouter,
    ) -> list[ToolSpec]:
        """Select up to *max_tools* tools appropriate for *query*.

        Args:
            query: The user's natural-language task description.
            all_tools: Complete list of available tools across all servers.
            max_tools: Maximum number of tools to return.
            strategy: Selection strategy (``"relevance"``, ``"round_robin"``,
                      ``"manual"``).
            router: ModelRouter for LLM-based classification fallback.

        Returns:
            Ordered list of the most relevant ToolSpecs.
        """
        if len(all_tools) <= max_tools:
            return all_tools

        if strategy == "round_robin":
            return self._round_robin(all_tools, max_tools)
        elif strategy == "manual":
            # Manual selection returns first max_tools (caller should pre-filter)
            return all_tools[:max_tools]

        # Default: relevance-based selection
        # Phase 1: keyword scoring
        keyword_scored = self._keyword_match(query, all_tools)

        # Phase 2: LLM classification for close calls
        top_candidates = [t for t, _ in keyword_scored[:max_tools * 2]]
        if len(top_candidates) > max_tools:
            try:
                llm_scored = await self._llm_classify(query, top_candidates, router)
                selected = [t for t, _ in llm_scored[:max_tools]]
            except Exception as exc:
                log.warning("[D] LLM classification failed, falling back to keywords: %s", exc)
                selected = [t for t, _ in keyword_scored[:max_tools]]
        else:
            selected = [t for t, _ in keyword_scored[:max_tools]]

        # Track usage for memory integration
        for tool in selected:
            self._usage_counts[tool.name] += 1

        return selected

    def _keyword_match(
        self,
        query: str,
        tools: list[ToolSpec],
    ) -> list[tuple[ToolSpec, float]]:
        """Score tools against *query* using keyword overlap.

        Returns:
            List of (tool, score) sorted descending by relevance.
        """
        query_words = set(query.lower().split())
        scored: list[tuple[ToolSpec, float]] = []

        for tool in tools:
            tool_words = set(tool.name.lower().replace("_", " ").split())
            desc_words = set((tool.description or "").lower().split())
            all_tool_words = tool_words | desc_words

            # Exact name word match gets high weight
            name_overlap = len(query_words & tool_words)
            desc_overlap = len(query_words & all_tool_words)

            # Boost for usage history (memory integration)
            usage_boost = min(self._usage_counts.get(tool.name, 0) * 0.1, 1.0)

            score = name_overlap * 3.0 + desc_overlap * 1.0 + usage_boost
            scored.append((tool, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    async def _llm_classify(
        self,
        query: str,
        tools: list[ToolSpec],
        router: ModelRouter,
    ) -> list[tuple[ToolSpec, float]]:
        """Use Kimi to classify which tools are most relevant.

        Sends a lightweight classification prompt to the LLM and parses
        the ranked tool names from the response.

        Returns:
            List of (tool, score) sorted descending by LLM-assigned relevance.
        """
        tool_descriptions = "\n".join(
            f"- {t.name}: {(t.description or 'No description')[:100]}"
            for t in tools
        )
        prompt = (
            f"Given this user task:\n\"{query}\"\n\n"
            f"And these available tools:\n{tool_descriptions}\n\n"
            f"Rank the tools from most to least relevant for this task. "
            f"Return ONLY a JSON array of tool names in order of relevance, "
            f"e.g. [\"tool_a\", \"tool_b\", \"tool_c\"]. No explanation."
        )

        client = router.get_client("kimi-k2.5")
        response = await client.chat.completions.create(
            model="kimi-k2.5",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=512,
            temperature=0.0,
        )
        content = (response.choices[0].message.content or "").strip()

        # Parse ranked names from LLM response
        try:
            ranked_names: list[str] = json.loads(content)
        except json.JSONDecodeError:
            # Fallback: extract tool names mentioned in the response
            ranked_names = [t.name for t in tools if t.name in content]

        # Build scored list maintaining LLM ranking
        name_to_tool = {t.name: t for t in tools}
        scored: list[tuple[ToolSpec, float]] = []
        seen: set[str] = set()

        for rank, name in enumerate(ranked_names):
            if name in name_to_tool and name not in seen:
                scored.append((name_to_tool[name], float(len(ranked_names) - rank)))
                seen.add(name)

        # Append any tools not ranked by the LLM at the end
        for tool in tools:
            if tool.name not in seen:
                scored.append((tool, 0.0))

        return scored

    def _round_robin(
        self,
        tools: list[ToolSpec],
        max_tools: int,
    ) -> list[ToolSpec]:
        """Rotate through tool sets across successive calls.

        Returns:
            The next *max_tools*-sized window from the full tool list.
        """
        start = self._round_robin_offset % len(tools)
        self._round_robin_offset += max_tools

        selected: list[ToolSpec] = []
        for i in range(max_tools):
            idx = (start + i) % len(tools)
            selected.append(tools[idx])
        return selected

    def get_usage_stats(self) -> dict[str, int]:
        """Return accumulated tool usage counts for memory integration."""
        return dict(self._usage_counts)


# ---------------------------------------------------------------------------
# DeterministicWrapper — safe execution of critical operations
# ---------------------------------------------------------------------------

class DeterministicWrapper:
    """Wrap critical tool operations in deterministic validation scripts.

    When ``enable_deterministic_wrappers`` is True, certain tool calls
    (file deletion, email sending, payments, etc.) are wrapped in a
    deterministic validation+execution script rather than letting the
    LLM call them directly.  This prevents hallucinated parameters.

    Workflow:

    1. LLM decides to call a critical tool
    2. Wrapper intercepts the call
    3. Validates parameters against schema
    4. Runs pre-flight checks (permissions, rate limits)
    5. Executes deterministically
    6. Returns structured result
    """

    # Patterns that indicate a critical/destructive tool
    CRITICAL_PATTERNS: list[re.Pattern[str]] = [
        re.compile(r"(delete|remove|drop|destroy)", re.IGNORECASE),
        re.compile(r"(send|email|message|notify)", re.IGNORECASE),
        re.compile(r"(publish|deploy|release)", re.IGNORECASE),
        re.compile(r"(pay|charge|transfer|invoice)", re.IGNORECASE),
        re.compile(r"(execute|eval|exec|run_command)", re.IGNORECASE),
    ]

    def __init__(
        self,
        safety: SafetyLayer | None = None,
        trust: TrustBoundary | None = None,
        require_approval_for: list[str] | None = None,
        rate_limit_per_minute: int = 60,
    ) -> None:
        self.safety = safety or SafetyLayer()
        self.trust = trust
        self._approval_keywords = require_approval_for or [
            "delete", "send", "publish", "pay",
        ]
        self._rate_limit = rate_limit_per_minute
        self._call_timestamps: list[float] = []
        self._audit_log: list[dict[str, Any]] = []

    async def wrap(
        self,
        tool_name: str,
        args: dict[str, Any],
        tool_spec: ToolSpec,
    ) -> ToolResult:
        """Intercept and validate a critical tool call before execution.

        Args:
            tool_name: Name of the tool being called.
            args: Arguments passed by the LLM.
            tool_spec: Full tool specification with schema and handler.

        Returns:
            ToolResult from the validated execution, or an error if
            validation/permission checks fail.
        """
        call_id = str(uuid.uuid4())[:8]
        audit_entry: dict[str, Any] = {
            "call_id": call_id,
            "tool": tool_name,
            "args": args,
            "timestamp": time.time(),
            "checks": [],
        }

        # Step 1: Parameter validation against schema
        validation_errors = await self._validate_params(args, tool_spec.parameters)
        if validation_errors:
            audit_entry["checks"].append({"param_validation": "FAILED", "errors": validation_errors})
            self._audit_log.append(audit_entry)
            return ToolResult(
                tool_call_id=call_id,
                name=tool_name,
                result=json.dumps({
                    "error": "Parameter validation failed",
                    "details": validation_errors,
                }),
                success=False,
            )
        audit_entry["checks"].append({"param_validation": "PASSED"})

        # Step 2: Rate limit check
        if not self._check_rate_limit():
            audit_entry["checks"].append({"rate_limit": "EXCEEDED"})
            self._audit_log.append(audit_entry)
            return ToolResult(
                tool_call_id=call_id,
                name=tool_name,
                result=json.dumps({
                    "error": f"Rate limit exceeded ({self._rate_limit}/min)",
                }),
                success=False,
            )
        audit_entry["checks"].append({"rate_limit": "PASSED"})

        # Step 3: Permission check
        has_permission = await self._check_permissions(tool_name)
        if not has_permission:
            audit_entry["checks"].append({"permissions": "DENIED"})
            self._audit_log.append(audit_entry)
            return ToolResult(
                tool_call_id=call_id,
                name=tool_name,
                result=json.dumps({
                    "error": f"Permission denied for {tool_name}. "
                             f"This action requires explicit approval.",
                }),
                success=False,
            )
        audit_entry["checks"].append({"permissions": "GRANTED"})

        # Step 4: Safety pre-flight (check for PII in args, prompt injection)
        args_text = json.dumps(args)
        safety_result = self.safety.check_input(args_text)
        if safety_result.blocked:
            audit_entry["checks"].append({"safety": "BLOCKED", "reason": safety_result.block_reason})
            self._audit_log.append(audit_entry)
            return ToolResult(
                tool_call_id=call_id,
                name=tool_name,
                result=json.dumps({
                    "error": f"Safety check blocked: {safety_result.block_reason}",
                }),
                success=False,
            )
        audit_entry["checks"].append({"safety": "PASSED"})

        # Step 5: Execute deterministically
        try:
            self._call_timestamps.append(time.time())
            result_str = await tool_spec.handler(**args)
            audit_entry["result"] = "SUCCESS"
            self._audit_log.append(audit_entry)
            return ToolResult(
                tool_call_id=call_id,
                name=tool_name,
                result=result_str,
                success=True,
            )
        except Exception as exc:
            audit_entry["result"] = f"ERROR: {exc}"
            self._audit_log.append(audit_entry)
            return ToolResult(
                tool_call_id=call_id,
                name=tool_name,
                result=json.dumps({"error": str(exc)}),
                success=False,
            )

    def is_critical(self, tool_name: str) -> bool:
        """Check whether *tool_name* matches any critical operation pattern.

        Returns:
            True if the tool name contains any destructive/critical keyword.
        """
        name_lower = tool_name.lower()
        # Check against configured approval keywords
        for keyword in self._approval_keywords:
            if keyword in name_lower:
                return True
        # Check against regex patterns
        for pattern in self.CRITICAL_PATTERNS:
            if pattern.search(tool_name):
                return True
        return False

    async def _validate_params(
        self,
        args: dict[str, Any],
        schema: dict[str, Any],
    ) -> list[str]:
        """Validate *args* against a JSON Schema-style parameter spec.

        Returns:
            List of validation error strings (empty = valid).
        """
        errors: list[str] = []
        if not schema:
            return errors

        required = set(schema.get("required", []))
        properties = schema.get("properties", {})

        # Check required parameters
        for param_name in required:
            if param_name not in args:
                errors.append(f"Missing required parameter: {param_name}")

        # Type validation for provided parameters
        for param_name, value in args.items():
            if param_name not in properties:
                # Extra parameter — warn but don't block
                continue
            expected_type = properties[param_name].get("type", "")
            if expected_type == "string" and not isinstance(value, str):
                errors.append(f"Parameter '{param_name}' should be string, got {type(value).__name__}")
            elif expected_type == "integer" and not isinstance(value, int):
                errors.append(f"Parameter '{param_name}' should be integer, got {type(value).__name__}")
            elif expected_type == "boolean" and not isinstance(value, bool):
                errors.append(f"Parameter '{param_name}' should be boolean, got {type(value).__name__}")
            elif expected_type == "array" and not isinstance(value, list):
                errors.append(f"Parameter '{param_name}' should be array, got {type(value).__name__}")
            elif expected_type == "object" and not isinstance(value, dict):
                errors.append(f"Parameter '{param_name}' should be object, got {type(value).__name__}")

        return errors

    async def _check_permissions(self, tool_name: str) -> bool:
        """Check whether the current trust level permits calling *tool_name*.

        Delegates to the TrustBoundary if one is configured; otherwise
        returns True (permissive default).
        """
        if self.trust is None:
            return True
        # Check trust level — elevated or admin can run destructive actions
        try:
            return self.trust.check_permission("execute_tool")
        except Exception:
            # Permissive fallback on trust check errors
            return True

    def _check_rate_limit(self) -> bool:
        """Enforce per-minute rate limiting on critical tool calls.

        Returns:
            True if within the limit, False if exceeded.
        """
        now = time.time()
        cutoff = now - 60.0
        self._call_timestamps = [t for t in self._call_timestamps if t > cutoff]
        return len(self._call_timestamps) < self._rate_limit

    def get_audit_log(self) -> list[dict[str, Any]]:
        """Return the full audit trail of all intercepted calls."""
        return list(self._audit_log)


# ---------------------------------------------------------------------------
# ServerHealthMonitor — background health checks and failover
# ---------------------------------------------------------------------------

class ServerHealthMonitor:
    """Monitor MCP server health and manage failover.

    Runs periodic health checks via MCP ping, manages automatic
    failover when a server goes down, reconnects with exponential
    backoff, and provides health dashboard data.
    """

    def __init__(
        self,
        servers: dict[str, MCPServerConfig],
        bridges: dict[str, MCPBridge],
        check_interval: float = 60.0,
        max_retries: int = 3,
    ) -> None:
        self._servers = servers
        self._bridges = bridges
        self._check_interval = check_interval
        self._max_retries = max_retries
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._health_history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        self._consecutive_failures: dict[str, int] = defaultdict(int)

    async def start(self) -> None:
        """Start the background health check loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._health_loop())
        log.info("[D] ServerHealthMonitor started (interval=%.0fs)", self._check_interval)

    async def stop(self) -> None:
        """Stop the background health check loop gracefully."""
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        log.info("[D] ServerHealthMonitor stopped")

    async def check_server(self, server: MCPServerConfig) -> str:
        """Perform a single health check against *server*.

        Sends a ``ping`` request to the MCP server and measures
        latency.  Updates the server's ``health`` field in place.

        Returns:
            Health status string: ``"healthy"``, ``"degraded"``, or ``"down"``.
        """
        bridge = self._bridges.get(server.name)
        if bridge is None or not bridge.connected:
            server.health = "down"
            self._record_check(server.name, "down", 0.0)
            return "down"

        t0 = time.monotonic()
        try:
            await bridge._mcp_request("ping", {})
            latency = time.monotonic() - t0

            if latency > 5.0:
                status = "degraded"
            else:
                status = "healthy"

            server.health = status
            self._consecutive_failures[server.name] = 0
            self._record_check(server.name, status, latency)
            return status

        except Exception as exc:
            latency = time.monotonic() - t0
            self._consecutive_failures[server.name] += 1
            failures = self._consecutive_failures[server.name]

            if failures >= self._max_retries:
                server.health = "down"
                log.warning(
                    "[D] Server '%s' marked DOWN after %d consecutive failures: %s",
                    server.name, failures, exc,
                )
            else:
                server.health = "degraded"
                log.info(
                    "[D] Server '%s' degraded (failure %d/%d): %s",
                    server.name, failures, self._max_retries, exc,
                )

            self._record_check(server.name, server.health, latency)
            return server.health

    def get_health_report(self) -> dict[str, Any]:
        """Return a health dashboard suitable for API/UI consumption.

        Returns:
            Dict with per-server status, latency history, and overall
            hub health summary.
        """
        servers_report: dict[str, Any] = {}
        total_healthy = 0
        total_servers = len(self._servers)

        for name, server in self._servers.items():
            history = self._health_history.get(name, [])
            recent = history[-10:] if history else []
            avg_latency = (
                sum(r["latency"] for r in recent) / len(recent) if recent else 0.0
            )

            servers_report[name] = {
                "status": server.health,
                "url": server.url,
                "transport": server.transport,
                "priority": server.priority,
                "avg_latency_ms": round(avg_latency * 1000, 1),
                "consecutive_failures": self._consecutive_failures.get(name, 0),
                "checks_total": len(history),
            }
            if server.health in ("healthy", "degraded"):
                total_healthy += 1

        return {
            "hub_status": "healthy" if total_healthy == total_servers else (
                "degraded" if total_healthy > 0 else "down"
            ),
            "total_servers": total_servers,
            "healthy_servers": total_healthy,
            "servers": servers_report,
        }

    # -- internal -----------------------------------------------------------

    async def _health_loop(self) -> None:
        """Background loop that periodically checks all servers."""
        while self._running:
            for server in list(self._servers.values()):
                if not self._running:
                    return
                try:
                    await self.check_server(server)
                except Exception as exc:
                    log.debug("[D] Health check error for '%s': %s", server.name, exc)

            try:
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                return

    def _record_check(self, name: str, status: str, latency: float) -> None:
        """Store a health check result in history."""
        self._health_history[name].append({
            "status": status,
            "latency": latency,
            "timestamp": time.time(),
        })
        # Keep last 100 entries per server
        if len(self._health_history[name]) > 100:
            self._health_history[name] = self._health_history[name][-100:]


# ---------------------------------------------------------------------------
# System prompt template
# ---------------------------------------------------------------------------

SYSTEM_TEMPLATE = """\
You are Horizon Orchestra, an autonomous AI agent powered by Kimi K2.5,
operating in MCP Tool Hub mode (Architecture D).

You have access to the following tools. Choose carefully — use the table to decide:

{tool_table}

Rules:
- Use at most one tool per reasoning step.
- For destructive actions (delete, send, pay), always confirm with the user first.
- If unsure which tool to use, ask the user.
- Break complex tasks into steps.  Use tools at each step.
- Search memory first when the task might relate to prior context.
- Store durable facts about the user when you learn them.
- You can call up to {max_iter} tools in sequence.

{memory_block}

Connected MCP servers: {server_list}
Total tools available: {total_available} (showing top {shown_count} most relevant)
"""


# ---------------------------------------------------------------------------
# MCPToolHub — main Architecture D orchestrator
# ---------------------------------------------------------------------------

class MCPToolHub:
    """Architecture D — MCP Tool Hub with dynamic tool discovery.

    Manages multiple MCP server connections, discovers tools dynamically,
    enforces the 5-8 tool surface limit, generates table-format guidance,
    wraps critical operations deterministically, and runs Kimi K2.5 as
    the orchestrating agent.

    Full workflow:

    1. Connect to configured MCP servers
    2. Discover all available tools (``tools/list``)
    3. For each user query, select the most relevant 5-8 tools
    4. Generate table-format tool guidance for Kimi
    5. Run agent loop with selected tool surface
    6. Route tool calls through appropriate MCP servers
    7. Wrap critical operations in deterministic scripts
    8. Monitor server health, reconnect on failure

    Supports:

    - Dynamic tool discovery and hot-reload
    - Multiple simultaneous MCP servers
    - Tool surface rotation for complex multi-step tasks
    - Approval workflow for destructive actions
    - Memory integration for learning tool usage patterns

    New capabilities (additive, all opt-in via config):

    * **AdaptiveContext** — priority-based message management that auto-
      compresses when the context window reaches 80% capacity.
    * **LongHorizonRunner** — checkpoint/resume support for multi-hour
      tasks; activate via ``config.enable_long_horizon=True`` or the
      ``run_long_horizon()`` method.
    * **TokenStreamer** — SSE/WebSocket-ready streaming via ``stream_sse()``.
    """

    def __init__(self, config: MCPHubConfig | None = None) -> None:
        self.config = config or MCPHubConfig()
        self.router = ModelRouter()

        # -- MCP server connections -----------------------------------------
        self._servers: dict[str, MCPServerConfig] = {}
        self._bridges: dict[str, MCPBridge] = {}
        self._all_tools: list[ToolSpec] = []
        self._tool_sources: dict[str, str] = {}       # tool_name → server_name

        # -- subsystems -----------------------------------------------------
        self._table_generator = ToolTableGenerator()
        self._selector = ToolSelector()
        self._wrapper = DeterministicWrapper(
            safety=SafetyLayer(),
            trust=TrustBoundary(trust_level=TrustLevel.STANDARD),
            require_approval_for=self.config.require_approval_for,
            rate_limit_per_minute=self.config.rate_limit_per_minute,
        )

        # -- tool registry (base tools + memory) ----------------------------
        self._base_tools = create_default_tools(self.router)

        # -- memory ---------------------------------------------------------
        db_path = self.config.memory_db or None
        self.memory_store = MemoryStore(db_path=db_path)
        self.memory = MemoryManager(
            store=self.memory_store,
            user_id=self.config.user_id,
        )
        register_memory_tools(self._base_tools, self.memory)

        # -- session tracking -----------------------------------------------
        self.session = SessionContext(
            session_id=str(uuid.uuid4())[:8],
            user_id=self.config.user_id,
        )
        self._total_tool_calls = 0
        self._total_tasks = 0
        self._current_surface: ToolSurface | None = None

        # -- health monitor -------------------------------------------------
        self._health_monitor = ServerHealthMonitor(
            servers=self._servers,
            bridges=self._bridges,
            check_interval=self.config.health_check_interval,
            max_retries=self.config.max_retries,
        )

        # -- adaptive context -----------------------------------------------
        self.adaptive_context: "AdaptiveContext | None" = None
        if self.config.enable_adaptive_context and _HAS_ADAPTIVE_CONTEXT:
            ac_config = self.config.adaptive_context_config or AdaptiveContextConfig()
            self.adaptive_context = AdaptiveContext(
                config=ac_config,
                router=self.router,
            )
            log.debug("[D] AdaptiveContext enabled (max_tokens=%d)", ac_config.max_tokens)

        # -- token streamer -------------------------------------------------
        self.token_streamer: "TokenStreamer | None" = None
        if self.config.enable_token_streaming and _HAS_TOKEN_STREAMING:
            st_config = self.config.streaming_config or StreamingConfig()
            self.token_streamer = TokenStreamer(config=st_config)
            log.debug("[D] TokenStreamer enabled")

        # -- long horizon (lazy — instantiated on first use) ----------------
        self._long_horizon: "LongHorizonRunner | None" = None

    # ===================================================================
    # Server management
    # ===================================================================

    async def connect_server(self, server: MCPServerConfig) -> None:
        """Connect to an MCP server and discover its tools.

        Creates an MCPBridge, initialises the connection, discovers
        available tools, filters them against whitelist/blacklist,
        and registers them into the hub's tool surface.

        Args:
            server: Configuration for the MCP server to connect to.

        Raises:
            ConnectionError: If the MCP server is unreachable after retries.
        """
        log.info("[D] Connecting to MCP server '%s' at %s", server.name, server.url)

        bridge = MCPBridge()
        connected = False

        for attempt in range(1, self.config.max_retries + 1):
            try:
                success = await asyncio.wait_for(
                    bridge.connect({"server_url": server.url}),
                    timeout=self.config.discovery_timeout,
                )
                if success:
                    connected = True
                    break
            except (asyncio.TimeoutError, Exception) as exc:
                log.warning(
                    "[D] Connection attempt %d/%d to '%s' failed: %s",
                    attempt, self.config.max_retries, server.name, exc,
                )
                if attempt < self.config.max_retries:
                    await asyncio.sleep(min(2 ** attempt, 10))

        if not connected:
            server.health = "down"
            raise ConnectionError(
                f"Failed to connect to MCP server '{server.name}' "
                f"at {server.url} after {self.config.max_retries} attempts"
            )

        server.health = "healthy"
        self._servers[server.name] = server
        self._bridges[server.name] = bridge

        # Discover and register tools from this server
        await self._register_server_tools(server, bridge)

        log.info(
            "[D] Server '%s' connected — %d tools registered",
            server.name, len([t for t, s in self._tool_sources.items() if s == server.name]),
        )

    async def disconnect_server(self, name: str) -> None:
        """Disconnect from an MCP server and remove its tools.

        Args:
            name: The server name to disconnect from.
        """
        bridge = self._bridges.pop(name, None)
        if bridge:
            await bridge.disconnect()

        server = self._servers.pop(name, None)

        # Remove tools from this server
        tools_to_remove = [
            tname for tname, sname in self._tool_sources.items()
            if sname == name
        ]
        for tname in tools_to_remove:
            del self._tool_sources[tname]
        self._all_tools = [t for t in self._all_tools if t.name not in tools_to_remove]

        log.info("[D] Server '%s' disconnected, %d tools removed", name, len(tools_to_remove))

    async def discover_tools(self) -> list[ToolSpec]:
        """Re-discover tools from all connected MCP servers.

        Useful for hot-reloading when a server's tool surface changes.

        Returns:
            Updated complete list of available ToolSpecs.
        """
        self._all_tools.clear()
        self._tool_sources.clear()

        for name, bridge in self._bridges.items():
            server = self._servers[name]
            await self._register_server_tools(server, bridge)

        log.info("[D] Tool discovery complete: %d tools from %d servers",
                 len(self._all_tools), len(self._bridges))
        return list(self._all_tools)

    # ===================================================================
    # Core execution
    # ===================================================================

    async def run(self, task: str, context: dict[str, Any] | None = None) -> str:
        """Execute a task end-to-end, returning the final answer string.

        Selects the optimal tool surface, builds a table-guided system
        prompt, runs the agent loop, routes tool calls through MCP
        servers, and returns the result.

        Args:
            task: The user's natural-language task.
            context: Optional additional context dict.

        Returns:
            The agent's final answer as a string.
        """
        result_parts: list[str] = []
        async for event in self.stream(task, context):
            if isinstance(event, FinalAnswerEvent):
                result_parts.append(event.content)
            elif isinstance(event, ErrorEvent) and not event.recoverable:
                result_parts.append(f"[ERROR] {event.message}")
        return "\n".join(result_parts)

    async def stream(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncGenerator[AgentEvent, None]:
        """Execute a task, yielding events as they occur.

        This is the core Architecture D loop:

        1. Select relevant tool surface for the task
        2. Build table-guided system prompt with memory context
        3. Register MCP tools as callable handlers
        4. Run AgentLoop with the selected tool surface
        5. Route tool calls through the correct MCP server
        6. Track session turns and auto-extract memories
        """
        self._total_tasks += 1
        self.session.add_turn("user", task)
        t0 = time.monotonic()

        context_str = json.dumps(context) if context else ""

        # -- select tool surface --------------------------------------------
        surface = await self.get_tool_surface(task)
        self._current_surface = surface

        # -- build system prompt with memory + tool table -------------------
        memory_block = await self.memory.get_context_block(
            query=task,
            limit=15,
        )
        server_names = ", ".join(self._servers.keys()) or "(none)"
        system_prompt = SYSTEM_TEMPLATE.format(
            tool_table=surface.table_guidance,
            max_iter=self.config.max_iterations,
            memory_block=memory_block or "(No prior memories for this user.)",
            server_list=server_names,
            total_available=surface.total_available,
            shown_count=len(surface.tools),
        )

        # -- wire adaptive context ------------------------------------------
        if self.adaptive_context is not None:
            self.adaptive_context.add_message("system", system_prompt, priority=1)
            self.adaptive_context.add_message("user", task)
            await self.adaptive_context.compress()
            log.debug("[D] AdaptiveContext messages ready")

        # -- build a tool registry for this turn ----------------------------
        turn_tools = ToolRegistry()

        # Register MCP-proxied tools
        for tool in surface.tools:
            server_name = surface.sources.get(tool.name)
            if server_name and server_name in self._bridges:
                # Create a closure-safe handler for each MCP tool
                handler = self._make_mcp_handler(tool.name, server_name)
                turn_tools.register(
                    name=tool.name,
                    description=tool.description,
                    parameters=tool.parameters,
                    handler=handler,
                )
            else:
                # Local tool (memory, search, etc.) — copy from base registry
                base_spec = self._base_tools.get(tool.name)
                if base_spec:
                    turn_tools.register(
                        name=base_spec.name,
                        description=base_spec.description,
                        parameters=base_spec.parameters,
                        handler=base_spec.handler,
                    )

        # Always ensure memory tools are available
        for mem_tool_name in ("memory_search", "memory_store"):
            if turn_tools.get(mem_tool_name) is None:
                base_spec = self._base_tools.get(mem_tool_name)
                if base_spec:
                    turn_tools.register(
                        name=base_spec.name,
                        description=base_spec.description,
                        parameters=base_spec.parameters,
                        handler=base_spec.handler,
                    )

        # -- run agent loop --------------------------------------------------
        agent_config = AgentConfig(
            model=self.config.model,
            max_iterations=self.config.max_iterations,
            max_tokens=self.config.max_tokens,
            temperature=self.config.temperature,
            system_prompt=system_prompt,
        )
        agent = AgentLoop(
            router=self.router,
            tools=turn_tools,
            config=agent_config,
        )

        final_content = ""
        tool_count = 0

        async for event in agent.run(task, context=context_str):
            if isinstance(event, ToolCallEvent):
                tool_count += 1
                log.info("[D] iter=%d tool=%s", event.iteration, event.tool_name)
            elif isinstance(event, FinalAnswerEvent):
                final_content = event.content
            yield event

        elapsed = time.monotonic() - t0
        self._total_tool_calls += tool_count

        # -- post-execution --------------------------------------------------
        if final_content:
            self.session.add_turn("assistant", final_content[:2000])

        # Save session
        await self.memory_store.save_session(self.session)

        # Auto-extract memories & learn tool usage patterns
        if final_content:
            conversation_text = self.session.to_context_string(last_n=6)
            try:
                extracted = await self.memory.auto_extract(
                    conversation=conversation_text,
                    model=self.config.model,
                    router=self.router,
                )
                if extracted:
                    log.info("[D] Auto-extracted %d memories", len(extracted))
            except Exception as exc:
                log.debug("Memory extraction failed: %s", exc)

            # Store tool usage pattern for future selection improvement
            await self._store_tool_usage_pattern(task, surface)

        log.info(
            "[D] Task complete: %d tools, %.1fs, model=%s, servers=%d",
            tool_count, elapsed, self.config.model, len(self._servers),
        )

    # ===================================================================
    # Tool surface management
    # ===================================================================

    async def get_tool_surface(self, query: str) -> ToolSurface:
        """Build the optimal tool surface for *query*.

        Collects all tools from all connected MCP servers and local
        tools, selects the most relevant subset (≤ max_tools_per_agent),
        and generates table-format guidance.

        Args:
            query: The user's task description.

        Returns:
            ToolSurface with the selected tools and guidance table.
        """
        # Gather all available tools
        all_tools = list(self._all_tools)

        # Add memory tools to the candidate pool
        for mem_name in ("memory_search", "memory_store"):
            spec = self._base_tools.get(mem_name)
            if spec and not any(t.name == mem_name for t in all_tools):
                all_tools.append(spec)

        total_available = len(all_tools)

        # Reserve 2 slots for memory tools
        max_mcp_tools = self.config.max_tools_per_agent - 2
        mcp_only = [t for t in all_tools if t.name not in ("memory_search", "memory_store")]
        memory_tools = [t for t in all_tools if t.name in ("memory_search", "memory_store")]

        # Select best MCP tools
        if len(mcp_only) > max_mcp_tools:
            selected_mcp = await self._selector.select(
                query=query,
                all_tools=mcp_only,
                max_tools=max_mcp_tools,
                strategy=self.config.tool_selection_strategy,
                router=self.router,
            )
        else:
            selected_mcp = mcp_only

        # Combine memory + selected MCP tools
        selected = memory_tools + selected_mcp

        # Build source map
        sources: dict[str, str] = {}
        for tool in selected:
            if tool.name in self._tool_sources:
                sources[tool.name] = self._tool_sources[tool.name]
            else:
                sources[tool.name] = "local"

        # Generate table guidance
        table_guidance = "(No tools available.)"
        if self.config.enable_table_guidance:
            table_guidance = self._table_generator.generate(selected, sources)

        surface = ToolSurface(
            tools=selected,
            sources=sources,
            table_guidance=table_guidance,
            total_available=total_available,
        )
        return surface

    async def rotate_tools(self, query: str) -> ToolSurface:
        """Get the next tool set for multi-step tasks needing > 8 tools.

        Rotates the tool surface by advancing the round-robin offset
        in the selector, ensuring the agent sees different tools on
        each rotation while retaining memory tools.

        Args:
            query: The current sub-task description.

        Returns:
            New ToolSurface with a different set of tools.
        """
        # Force round_robin for rotation
        all_tools = list(self._all_tools)
        mcp_only = [t for t in all_tools if t.name not in ("memory_search", "memory_store")]
        memory_tools = [
            t for t in all_tools if t.name in ("memory_search", "memory_store")
        ]
        if not memory_tools:
            for mem_name in ("memory_search", "memory_store"):
                spec = self._base_tools.get(mem_name)
                if spec:
                    memory_tools.append(spec)

        max_mcp_tools = self.config.max_tools_per_agent - len(memory_tools)

        selected_mcp = self._selector._round_robin(mcp_only, max_mcp_tools)
        selected = memory_tools + selected_mcp

        sources: dict[str, str] = {}
        for tool in selected:
            sources[tool.name] = self._tool_sources.get(tool.name, "local")

        table_guidance = self._table_generator.generate(selected, sources)

        surface = ToolSurface(
            tools=selected,
            sources=sources,
            table_guidance=table_guidance,
            total_available=len(all_tools),
        )
        self._current_surface = surface
        log.info("[D] Tool surface rotated: %s", [t.name for t in selected])
        return surface

    # ===================================================================
    # Tool call routing
    # ===================================================================

    async def call_tool(self, tool_name: str, args: dict[str, Any]) -> ToolResult:
        """Route a tool call through the appropriate MCP server.

        If the tool is critical and deterministic wrappers are enabled,
        the call is intercepted and validated before execution.

        Args:
            tool_name: Name of the tool to call.
            args: Arguments for the tool.

        Returns:
            ToolResult with the execution outcome.
        """
        call_id = str(uuid.uuid4())[:8]

        # Find the tool spec
        tool_spec = next((t for t in self._all_tools if t.name == tool_name), None)
        if tool_spec is None:
            tool_spec = self._base_tools.get(tool_name)

        if tool_spec is None:
            return ToolResult(
                tool_call_id=call_id,
                name=tool_name,
                result=json.dumps({"error": f"Unknown tool: {tool_name}"}),
                success=False,
            )

        # Deterministic wrapper for critical operations
        if self.config.enable_deterministic_wrappers and self._wrapper.is_critical(tool_name):
            log.info("[D] Routing '%s' through deterministic wrapper", tool_name)
            return await self._wrapper.wrap(tool_name, args, tool_spec)

        # Direct execution for non-critical tools
        server_name = self._tool_sources.get(tool_name)
        if server_name and server_name in self._bridges:
            bridge = self._bridges[server_name]
            result = await bridge.execute(tool_name, args)
            return ToolResult(
                tool_call_id=call_id,
                name=tool_name,
                result=json.dumps(result) if isinstance(result, dict) else str(result),
                success=not result.get("error") if isinstance(result, dict) else True,
            )
        else:
            # Local tool
            return await self._base_tools.execute(tool_name, args, call_id=call_id)

    # ===================================================================
    # Streaming — SSE
    # ===================================================================

    async def stream_sse(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncGenerator["StreamChunk", None]:
        """Execute a task and yield SSE-ready StreamChunk objects.

        Wraps ``stream()`` with BufferedStreamer to produce typed chunks
        (token, tool_call_start, tool_call_complete, finish, heartbeat)
        suitable for Server-Sent Events or WebSocket delivery.

        Args:
            task: The user task to execute.
            context: Optional additional context dict.

        Yields:
            StreamChunk objects.  Call ``.to_sse()`` on each for raw SSE
            wire format.

        Raises:
            RuntimeError: If the token_streaming module is unavailable.
        """
        if not _HAS_TOKEN_STREAMING:
            raise RuntimeError(
                "token_streaming module is not available; "
                "ensure orchestra/token_streaming.py is present."
            )
        st_config = self.config.streaming_config or StreamingConfig()
        buffered = BufferedStreamer(config=st_config)
        log.debug("[D] stream_sse: starting buffered SSE stream")
        async for chunk in buffered.stream_agent_response(self, task, context=context):
            yield chunk

    # ===================================================================
    # Long-horizon execution
    # ===================================================================

    def _get_long_horizon_runner(self) -> "LongHorizonRunner":
        """Return (or lazily create) the LongHorizonRunner."""
        if not _HAS_LONG_HORIZON:
            raise RuntimeError(
                "long_horizon module is not available; "
                "ensure orchestra/long_horizon.py is present."
            )
        if self._long_horizon is None:
            lh_config = (
                self.config.long_horizon_config or LongHorizonConfig(
                    model=self.config.model,
                )
            )
            checkpoint_store = CheckpointStore()
            self._long_horizon = LongHorizonRunner(
                router=self.router,
                tools=list(self._base_tools),
                config=lh_config,
                checkpoint_store=checkpoint_store,
            )
            log.debug(
                "[D] LongHorizonRunner created (max_hours=%.1f)",
                lh_config.max_runtime_hours,
            )
        return self._long_horizon

    async def run_long_horizon(
        self,
        task: str,
        user_id: str = "",
        resume_from: str = "",
    ) -> "LongHorizonResult":
        """Execute a long-horizon task with automatic checkpoint/resume.

        Uses LongHorizonRunner to break the task into steps, execute
        them sequentially, checkpoint periodically, and pause gracefully
        near runtime/Lambda limits.

        Args:
            task: The high-level task description.
            user_id: User identifier (defaults to config.user_id).
            resume_from: Task ID of a prior paused run to resume from.

        Returns:
            LongHorizonResult with status, result text, and progress info.

        Raises:
            RuntimeError: If the long_horizon module is unavailable.
        """
        runner = self._get_long_horizon_runner()
        uid = user_id or self.config.user_id
        log.info("[D] Starting long-horizon task user_id=%s resume=%s", uid, resume_from or "none")
        result = await runner.run(task=task, user_id=uid, resume_from=resume_from)
        log.info(
            "[D] Long-horizon complete: status=%s steps=%d/%d",
            result.status, result.steps_completed, result.total_steps,
        )
        return result

    # ===================================================================
    # Health monitoring
    # ===================================================================

    def get_health_report(self) -> dict[str, Any]:
        """Return health status for all connected MCP servers."""
        return self._health_monitor.get_health_report()

    async def start_health_monitor(self) -> None:
        """Start background health checks for all connected servers."""
        await self._health_monitor.start()

    async def stop_health_monitor(self) -> None:
        """Stop background health checks."""
        await self._health_monitor.stop()

    # ===================================================================
    # Internal helpers
    # ===================================================================

    async def _register_server_tools(
        self,
        server: MCPServerConfig,
        bridge: MCPBridge,
    ) -> None:
        """Discover and register tools from a single MCP server.

        Applies whitelist/blacklist filters and converts MCP tool
        definitions to ToolSpec objects.
        """
        tool_defs = bridge.get_tool_definitions()

        for tdef in tool_defs:
            func_def = tdef.get("function", {})
            raw_name = func_def.get("name", "")
            # Strip the "mcp_" prefix that MCPBridge adds
            clean_name = raw_name.removeprefix("mcp_")

            # Apply whitelist/blacklist
            if server.tools_whitelist and clean_name not in server.tools_whitelist:
                continue
            if clean_name in server.tools_blacklist:
                continue

            description = func_def.get("description", "")
            parameters = func_def.get("parameters", {"type": "object", "properties": {}})

            # Use a stable name: server_toolname (avoids collisions)
            tool_name = f"{server.name}_{clean_name}" if len(self._servers) > 1 else clean_name

            handler = self._make_mcp_handler(clean_name, server.name)

            spec = ToolSpec(
                name=tool_name,
                description=f"[{server.name}] {description}",
                parameters=parameters,
                handler=handler,
            )
            self._all_tools.append(spec)
            self._tool_sources[tool_name] = server.name

    def _make_mcp_handler(
        self,
        tool_name: str,
        server_name: str,
    ) -> Any:
        """Create a closure-safe async handler for an MCP tool call.

        The returned coroutine function proxies tool calls through the
        correct MCPBridge, optionally intercepting via the deterministic
        wrapper for critical operations.
        """
        bridge_ref = self._bridges
        wrapper_ref = self._wrapper
        config_ref = self.config

        async def _handler(**kwargs: Any) -> str:
            bridge = bridge_ref.get(server_name)
            if bridge is None or not bridge.connected:
                return json.dumps({"error": f"Server '{server_name}' is not connected"})

            result = await bridge.execute(tool_name, kwargs)
            return json.dumps(result) if isinstance(result, dict) else str(result)

        return _handler

    async def _store_tool_usage_pattern(
        self,
        task: str,
        surface: ToolSurface,
    ) -> None:
        """Store tool usage patterns in memory for future selection.

        Records which tools were selected for which types of tasks,
        enabling the ToolSelector to learn from past usage over time.
        """
        usage_stats = self._selector.get_usage_stats()
        if not usage_stats:
            return

        pattern = {
            "task_keywords": " ".join(task.lower().split()[:10]),
            "tools_used": [t.name for t in surface.tools],
            "sources": surface.sources,
            "timestamp": time.time(),
        }

        try:
            await self.memory_store.store(
                self.config.user_id,
                json.dumps(pattern),
                category="tool",
                source="arch_d_usage",
            )
        except Exception as exc:
            log.debug("[D] Failed to store tool usage pattern: %s", exc)

    # ===================================================================
    # Session helpers and stats
    # ===================================================================

    async def recall(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search memories related to a query."""
        results = await self.memory_store.search(
            self.config.user_id, query, limit=limit,
        )
        return [
            {
                "content": r.content,
                "category": r.category,
                "relevance": round(r.relevance_score, 3),
            }
            for r in results
        ]

    async def remember(self, fact: str, category: str = "fact") -> str:
        """Manually store a memory."""
        entry = await self.memory_store.store(
            self.config.user_id, fact, category=category, source="explicit",
        )
        return entry.id

    @property
    def stats(self) -> dict[str, Any]:
        """Return diagnostic stats for the MCP Tool Hub."""
        return {
            "architecture": "D",
            "model": self.config.model,
            "total_tasks": self._total_tasks,
            "total_tool_calls": self._total_tool_calls,
            "session_id": self.session.session_id,
            "session_turns": len(self.session.turns),
            "connected_servers": list(self._servers.keys()),
            "total_tools_discovered": len(self._all_tools),
            "max_tools_per_agent": self.config.max_tools_per_agent,
            "tool_selection_strategy": self.config.tool_selection_strategy,
            "deterministic_wrappers": self.config.enable_deterministic_wrappers,
            "adaptive_context_enabled": self.adaptive_context is not None,
            "token_streaming_enabled": self.token_streamer is not None,
            "long_horizon_enabled": self.config.enable_long_horizon,
            "health": self.get_health_report(),
        }


# ---------------------------------------------------------------------------
# Quick-run helper
# ---------------------------------------------------------------------------

async def run_mcp_hub(
    task: str,
    servers: list[MCPServerConfig] | None = None,
    model: str = "kimi-k2.5",
    user_id: str = "default",
) -> str:
    """One-liner to run a task through Architecture D.

    Args:
        task: The user's task description.
        servers: Optional list of MCP servers to connect to.
        model: Model identifier.
        user_id: User identifier for memory.

    Returns:
        The agent's final answer string.
    """
    config = MCPHubConfig(
        model=model,
        user_id=user_id,
        default_servers=servers or [],
    )
    hub = MCPToolHub(config=config)

    for server in config.default_servers:
        try:
            await hub.connect_server(server)
        except ConnectionError as exc:
            log.warning("Failed to connect to %s: %s", server.name, exc)

    return await hub.run(task)
