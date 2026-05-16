"""
error_taxonomy.py — Comprehensive error taxonomy for Horizon Orchestra.

Defines 60+ error types across 8 categories (NETWORK, MODEL, CONTENT,
EXECUTION, CONTEXT, STREAMING, ORCHESTRATION, SAFETY). Each ErrorSpec
carries recovery strategy, user-facing message, and internal action.

The global ERROR_REGISTRY dict maps error codes to their ErrorSpec.
ErrorTaxonomy provides convenience lookup/classification helpers.
"""
from __future__ import annotations

__all__ = [
    "ErrorCategory",
    "ErrorSpec",
    "ERROR_REGISTRY",
    "ErrorTaxonomy",
]

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Category enum
# ---------------------------------------------------------------------------

class ErrorCategory(str, Enum):
    """Top-level error dimension."""
    NETWORK = "NETWORK"
    MODEL = "MODEL"
    CONTENT = "CONTENT"
    EXECUTION = "EXECUTION"
    CONTEXT = "CONTEXT"
    STREAMING = "STREAMING"
    ORCHESTRATION = "ORCHESTRATION"
    SAFETY = "SAFETY"


# ---------------------------------------------------------------------------
# ErrorSpec dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ErrorSpec:
    """Immutable specification for a single error type.

    Attributes:
        code: Unique machine-readable identifier, e.g. ``"MODEL_RATE_LIMIT_HARD"``.
        category: One of the eight :class:`ErrorCategory` values.
        severity: 1 (informational) – 10 (catastrophic).
        is_retryable: Whether the same request can be re-sent.
        is_recoverable: Whether *any* recovery path exists.
        recovery_strategy: Primary recovery strategy name.
        max_recovery_attempts: Hard cap on recovery tries.
        recovery_timeout_ms: Wall-clock limit for recovery.
        user_facing_message: Human-friendly status shown to the user.
        internal_action: What the system does internally.
    """
    code: str
    category: str
    severity: int
    is_retryable: bool
    is_recoverable: bool
    recovery_strategy: str
    max_recovery_attempts: int
    recovery_timeout_ms: int
    user_facing_message: str
    internal_action: str


# ---------------------------------------------------------------------------
# Full registry: 64 error types across 8 categories
# ---------------------------------------------------------------------------

def _build_registry() -> dict[str, ErrorSpec]:
    """Construct the global error registry."""
    specs: list[ErrorSpec] = []

    # ── NETWORK (10 types) ────────────────────────────────────────────────
    specs.extend([
        ErrorSpec(
            code="NETWORK_CONNECTION_REFUSED",
            category="NETWORK", severity=7, is_retryable=True, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=3, recovery_timeout_ms=5000,
            user_facing_message="Connecting to an alternative service…",
            internal_action="Failover to next healthy provider in chain",
        ),
        ErrorSpec(
            code="NETWORK_DNS_RESOLUTION",
            category="NETWORK", severity=8, is_retryable=True, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=2, recovery_timeout_ms=3000,
            user_facing_message="Resolving connection, one moment…",
            internal_action="Switch provider; log DNS failure for ops alerting",
        ),
        ErrorSpec(
            code="NETWORK_SSL_CERTIFICATE",
            category="NETWORK", severity=9, is_retryable=False, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=1, recovery_timeout_ms=2000,
            user_facing_message="Securing connection via alternate route…",
            internal_action="Failover provider; alert security team about SSL issue",
        ),
        ErrorSpec(
            code="NETWORK_TIMEOUT_CONNECT",
            category="NETWORK", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="exponential_backoff",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Connection is slow — retrying…",
            internal_action="Retry with exponential backoff; record latency spike",
        ),
        ErrorSpec(
            code="NETWORK_TIMEOUT_READ",
            category="NETWORK", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="exponential_backoff",
            max_recovery_attempts=3, recovery_timeout_ms=15000,
            user_facing_message="Waiting for response — retrying…",
            internal_action="Retry with backoff; consider increasing read timeout",
        ),
        ErrorSpec(
            code="NETWORK_TIMEOUT_WRITE",
            category="NETWORK", severity=5, is_retryable=True, is_recoverable=True,
            recovery_strategy="exponential_backoff",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Sending request again…",
            internal_action="Retry with backoff; check payload size",
        ),
        ErrorSpec(
            code="NETWORK_BANDWIDTH_EXHAUSTED",
            category="NETWORK", severity=7, is_retryable=True, is_recoverable=True,
            recovery_strategy="async_queue",
            max_recovery_attempts=2, recovery_timeout_ms=30000,
            user_facing_message="High traffic — queuing your request…",
            internal_action="Queue request; throttle concurrent connections",
        ),
        ErrorSpec(
            code="NETWORK_PROXY_FAILURE",
            category="NETWORK", severity=7, is_retryable=True, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=2, recovery_timeout_ms=5000,
            user_facing_message="Routing via alternate path…",
            internal_action="Bypass proxy; failover to direct connection or alt provider",
        ),
        ErrorSpec(
            code="NETWORK_HOST_UNREACHABLE",
            category="NETWORK", severity=8, is_retryable=True, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=2, recovery_timeout_ms=5000,
            user_facing_message="Service temporarily unreachable — switching provider…",
            internal_action="Mark provider unhealthy; failover immediately",
        ),
        ErrorSpec(
            code="NETWORK_PACKET_LOSS",
            category="NETWORK", severity=5, is_retryable=True, is_recoverable=True,
            recovery_strategy="exponential_backoff",
            max_recovery_attempts=4, recovery_timeout_ms=8000,
            user_facing_message="Experiencing network instability — retrying…",
            internal_action="Retry with jitter; log network quality metrics",
        ),
    ])

    # ── MODEL (11 types) ──────────────────────────────────────────────────
    specs.extend([
        ErrorSpec(
            code="MODEL_RATE_LIMIT_SOFT",
            category="MODEL", severity=4, is_retryable=True, is_recoverable=True,
            recovery_strategy="exponential_backoff",
            max_recovery_attempts=5, recovery_timeout_ms=60000,
            user_facing_message="Processing your request…",
            internal_action="Backoff with decorrelated jitter; rotate API keys",
        ),
        ErrorSpec(
            code="MODEL_RATE_LIMIT_HARD",
            category="MODEL", severity=7, is_retryable=False, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=3, recovery_timeout_ms=5000,
            user_facing_message="Switching to a faster lane…",
            internal_action="Immediate provider failover; queue for original provider later",
        ),
        ErrorSpec(
            code="MODEL_CONTEXT_WINDOW_EXCEEDED",
            category="MODEL", severity=6, is_retryable=False, is_recoverable=True,
            recovery_strategy="truncate_context",
            max_recovery_attempts=2, recovery_timeout_ms=3000,
            user_facing_message="Optimizing context for best results…",
            internal_action="Truncate oldest messages; compress via summarization",
        ),
        ErrorSpec(
            code="MODEL_TOKEN_BUDGET_EXHAUSTED",
            category="MODEL", severity=8, is_retryable=False, is_recoverable=True,
            recovery_strategy="model_downgrade",
            max_recovery_attempts=2, recovery_timeout_ms=3000,
            user_facing_message="Adjusting for continued assistance…",
            internal_action="Downgrade to cheaper model; notify billing layer",
        ),
        ErrorSpec(
            code="MODEL_UNSUPPORTED_FEATURE",
            category="MODEL", severity=5, is_retryable=False, is_recoverable=True,
            recovery_strategy="model_downgrade",
            max_recovery_attempts=2, recovery_timeout_ms=2000,
            user_facing_message="Adjusting approach for best results…",
            internal_action="Re-route to a model that supports the requested feature",
        ),
        ErrorSpec(
            code="MODEL_DEPRECATED",
            category="MODEL", severity=6, is_retryable=False, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=1, recovery_timeout_ms=2000,
            user_facing_message="Upgrading to latest model…",
            internal_action="Switch to successor model; log deprecation notice",
        ),
        ErrorSpec(
            code="MODEL_OVERLOADED",
            category="MODEL", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="High demand — routing optimally…",
            internal_action="Try alternate provider; if all overloaded, queue with ETA",
        ),
        ErrorSpec(
            code="MODEL_UNAVAILABLE",
            category="MODEL", severity=8, is_retryable=True, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Connecting to available service…",
            internal_action="Mark model unavailable; failover to fallback chain",
        ),
        ErrorSpec(
            code="MODEL_INVALID_API_KEY",
            category="MODEL", severity=9, is_retryable=False, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=1, recovery_timeout_ms=2000,
            user_facing_message="Authenticating via alternate route…",
            internal_action="Rotate API key; if all keys invalid, alert ops",
        ),
        ErrorSpec(
            code="MODEL_QUOTA_EXHAUSTED",
            category="MODEL", severity=8, is_retryable=False, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=2, recovery_timeout_ms=3000,
            user_facing_message="Switching service provider…",
            internal_action="Failover to alternate provider; notify billing",
        ),
        ErrorSpec(
            code="MODEL_BILLING_REQUIRED",
            category="MODEL", severity=9, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=2000,
            user_facing_message="Account configuration needed — using backup service…",
            internal_action="Fall back to free-tier model; alert ops about billing issue",
        ),
    ])

    # ── CONTENT (10 types) ────────────────────────────────────────────────
    specs.extend([
        ErrorSpec(
            code="CONTENT_OUTPUT_TRUNCATED",
            category="CONTENT", severity=4, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=2, recovery_timeout_ms=15000,
            user_facing_message="Completing response…",
            internal_action="Re-issue with 'continue from last coherent sentence'",
        ),
        ErrorSpec(
            code="CONTENT_HALLUCINATED_TOOL_CALL",
            category="CONTENT", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=2, recovery_timeout_ms=10000,
            user_facing_message="Verifying tool usage…",
            internal_action="Strip hallucinated tool call; re-prompt with tool list reminder",
        ),
        ErrorSpec(
            code="CONTENT_MALFORMED_JSON",
            category="CONTENT", severity=5, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Formatting response…",
            internal_action="Attempt JSON repair; if fails, re-prompt with stricter format instruction",
        ),
        ErrorSpec(
            code="CONTENT_TOOL_CALL_MISMATCH",
            category="CONTENT", severity=5, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=2, recovery_timeout_ms=8000,
            user_facing_message="Adjusting tool parameters…",
            internal_action="Validate tool call args against schema; re-prompt if mismatch",
        ),
        ErrorSpec(
            code="CONTENT_EMPTY_RESPONSE",
            category="CONTENT", severity=5, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Generating response…",
            internal_action="Retry with slightly modified temperature; log empty response",
        ),
        ErrorSpec(
            code="CONTENT_REPETITION_LOOP",
            category="CONTENT", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="model_downgrade",
            max_recovery_attempts=2, recovery_timeout_ms=8000,
            user_facing_message="Refining response…",
            internal_action="Detect loop; increase temperature; try alternate model",
        ),
        ErrorSpec(
            code="CONTENT_SELF_REFERENTIAL_ANSWER",
            category="CONTENT", severity=4, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=2, recovery_timeout_ms=8000,
            user_facing_message="Refining answer…",
            internal_action="Re-prompt with explicit 'answer the question directly' instruction",
        ),
        ErrorSpec(
            code="CONTENT_INCOHERENT_OUTPUT",
            category="CONTENT", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="model_downgrade",
            max_recovery_attempts=2, recovery_timeout_ms=10000,
            user_facing_message="Regenerating response…",
            internal_action="Discard output; try with lower temperature or alternate model",
        ),
        ErrorSpec(
            code="CONTENT_CODE_SYNTAX_ERROR",
            category="CONTENT", severity=4, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=2, recovery_timeout_ms=10000,
            user_facing_message="Fixing code…",
            internal_action="Feed syntax error back as follow-up; request correction",
        ),
        ErrorSpec(
            code="CONTENT_SCHEMA_VIOLATION",
            category="CONTENT", severity=5, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Adjusting output format…",
            internal_action="Validate against schema; include violation details in re-prompt",
        ),
    ])

    # ── EXECUTION (8 types) ───────────────────────────────────────────────
    specs.extend([
        ErrorSpec(
            code="EXECUTION_TOOL_TIMEOUT",
            category="EXECUTION", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="exponential_backoff",
            max_recovery_attempts=3, recovery_timeout_ms=30000,
            user_facing_message="Tool is taking longer than expected — retrying…",
            internal_action="Retry tool execution; consider increasing timeout",
        ),
        ErrorSpec(
            code="EXECUTION_TOOL_EXCEPTION",
            category="EXECUTION", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=2, recovery_timeout_ms=10000,
            user_facing_message="Retrying operation…",
            internal_action="Retry with sanitised inputs; log exception details",
        ),
        ErrorSpec(
            code="EXECUTION_SANDBOX_CRASH",
            category="EXECUTION", severity=8, is_retryable=True, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=2, recovery_timeout_ms=15000,
            user_facing_message="Restarting secure environment…",
            internal_action="Respawn sandbox; restore state from last checkpoint",
        ),
        ErrorSpec(
            code="EXECUTION_MEMORY_ALLOCATION_FAILED",
            category="EXECUTION", severity=8, is_retryable=True, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=5000,
            user_facing_message="Optimizing resource usage…",
            internal_action="Free caches; reduce batch size; retry with smaller context",
        ),
        ErrorSpec(
            code="EXECUTION_FILE_NOT_FOUND",
            category="EXECUTION", severity=4, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=2000,
            user_facing_message="File not found — adjusting approach…",
            internal_action="Report missing file to agent; let agent decide next step",
        ),
        ErrorSpec(
            code="EXECUTION_PERMISSION_DENIED",
            category="EXECUTION", severity=7, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=2000,
            user_facing_message="Permission issue — finding alternative…",
            internal_action="Log permission error; attempt operation via elevated sandbox",
        ),
        ErrorSpec(
            code="EXECUTION_DISK_FULL",
            category="EXECUTION", severity=9, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=5000,
            user_facing_message="Clearing space for your task…",
            internal_action="Trigger garbage collection; prune temp files; alert ops",
        ),
        ErrorSpec(
            code="EXECUTION_PROCESS_KILLED",
            category="EXECUTION", severity=8, is_retryable=True, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=2, recovery_timeout_ms=10000,
            user_facing_message="Restarting process…",
            internal_action="Restart process with resource limits; restore from checkpoint",
        ),
    ])

    # ── CONTEXT (5 types) ─────────────────────────────────────────────────
    specs.extend([
        ErrorSpec(
            code="CONTEXT_CORRUPTED",
            category="CONTEXT", severity=8, is_retryable=False, is_recoverable=True,
            recovery_strategy="cache_lookup",
            max_recovery_attempts=1, recovery_timeout_ms=3000,
            user_facing_message="Rebuilding context…",
            internal_action="Discard corrupted context; rebuild from conversation history",
        ),
        ErrorSpec(
            code="CONTEXT_TOO_LARGE",
            category="CONTEXT", severity=5, is_retryable=False, is_recoverable=True,
            recovery_strategy="truncate_context",
            max_recovery_attempts=2, recovery_timeout_ms=3000,
            user_facing_message="Optimizing context window…",
            internal_action="Summarize old messages; keep most recent + system prompt",
        ),
        ErrorSpec(
            code="CONTEXT_MEMORY_STORE_UNAVAILABLE",
            category="CONTEXT", severity=7, is_retryable=True, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Memory system reconnecting…",
            internal_action="Proceed without memory store; queue memory writes for later",
        ),
        ErrorSpec(
            code="CONTEXT_EMBEDDING_FAILURE",
            category="CONTEXT", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="provider_failover",
            max_recovery_attempts=2, recovery_timeout_ms=5000,
            user_facing_message="Optimizing search…",
            internal_action="Failover to alternate embedding provider; fallback to keyword search",
        ),
        ErrorSpec(
            code="CONTEXT_VECTOR_INDEX_CORRUPTED",
            category="CONTEXT", severity=8, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=5000,
            user_facing_message="Rebuilding search index…",
            internal_action="Drop to keyword search; trigger async index rebuild",
        ),
    ])

    # ── STREAMING (6 types) ───────────────────────────────────────────────
    specs.extend([
        ErrorSpec(
            code="STREAMING_SSE_DISCONNECTED",
            category="STREAMING", severity=5, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Reconnecting stream…",
            internal_action="Resume SSE from last event ID; heal buffer gap",
        ),
        ErrorSpec(
            code="STREAMING_WEBSOCKET_CLOSED",
            category="STREAMING", severity=5, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Reconnecting…",
            internal_action="Re-establish WebSocket; replay missed events",
        ),
        ErrorSpec(
            code="STREAMING_PARTIAL_CHUNK",
            category="STREAMING", severity=3, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=5, recovery_timeout_ms=5000,
            user_facing_message="Receiving data…",
            internal_action="Buffer partial chunk; wait for completion or request re-send",
        ),
        ErrorSpec(
            code="STREAMING_OUT_OF_ORDER_CHUNKS",
            category="STREAMING", severity=4, is_retryable=False, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=2, recovery_timeout_ms=5000,
            user_facing_message="Organizing response…",
            internal_action="Re-order chunks by sequence number; request re-stream if gap detected",
        ),
        ErrorSpec(
            code="STREAMING_DUPLICATE_CHUNK",
            category="STREAMING", severity=2, is_retryable=False, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=1, recovery_timeout_ms=1000,
            user_facing_message="Processing response…",
            internal_action="Deduplicate based on content hash; continue normally",
        ),
        ErrorSpec(
            code="STREAMING_MISSING_HEARTBEAT",
            category="STREAMING", severity=4, is_retryable=True, is_recoverable=True,
            recovery_strategy="retry_same",
            max_recovery_attempts=3, recovery_timeout_ms=15000,
            user_facing_message="Checking connection…",
            internal_action="Send ping; if no pong within timeout, reconnect stream",
        ),
    ])

    # ── ORCHESTRATION (5 types) ───────────────────────────────────────────
    specs.extend([
        ErrorSpec(
            code="ORCHESTRATION_SWARM_DEADLOCK",
            category="ORCHESTRATION", severity=9, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=5000,
            user_facing_message="Reorganizing task execution…",
            internal_action="Kill deadlocked agents; restart with simplified dependency graph",
        ),
        ErrorSpec(
            code="ORCHESTRATION_CIRCULAR_DEPENDENCY",
            category="ORCHESTRATION", severity=8, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=3000,
            user_facing_message="Optimizing task order…",
            internal_action="Detect cycle via topological sort; break least-cost edge",
        ),
        ErrorSpec(
            code="ORCHESTRATION_AGENT_STARVATION",
            category="ORCHESTRATION", severity=6, is_retryable=True, is_recoverable=True,
            recovery_strategy="async_queue",
            max_recovery_attempts=3, recovery_timeout_ms=15000,
            user_facing_message="Allocating resources…",
            internal_action="Priority-boost starved agent; preempt low-priority work",
        ),
        ErrorSpec(
            code="ORCHESTRATION_COORDINATOR_CRASH",
            category="ORCHESTRATION", severity=10, is_retryable=True, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=2, recovery_timeout_ms=10000,
            user_facing_message="Restarting coordination…",
            internal_action="Elect new coordinator; replay incomplete tasks from checkpoint",
        ),
        ErrorSpec(
            code="ORCHESTRATION_LONG_HORIZON_CHECKPOINT_FAIL",
            category="ORCHESTRATION", severity=7, is_retryable=True, is_recoverable=True,
            recovery_strategy="cache_lookup",
            max_recovery_attempts=3, recovery_timeout_ms=10000,
            user_facing_message="Saving progress…",
            internal_action="Retry checkpoint write; fall back to in-memory state",
        ),
    ])

    # ── SAFETY (5 types) ──────────────────────────────────────────────────
    specs.extend([
        ErrorSpec(
            code="SAFETY_FILTER_TRIGGERED",
            category="SAFETY", severity=6, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=2000,
            user_facing_message="Content policy applied — adjusting response…",
            internal_action="Re-prompt with safety-aware framing; log trigger for review",
        ),
        ErrorSpec(
            code="SAFETY_TRUST_BOUNDARY_VIOLATED",
            category="SAFETY", severity=9, is_retryable=False, is_recoverable=False,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=0, recovery_timeout_ms=1000,
            user_facing_message="Security check triggered — operation blocked.",
            internal_action="Block operation; alert security team; log full context",
        ),
        ErrorSpec(
            code="SAFETY_AUDIT_LOG_FAILED",
            category="SAFETY", severity=7, is_retryable=True, is_recoverable=True,
            recovery_strategy="async_queue",
            max_recovery_attempts=5, recovery_timeout_ms=30000,
            user_facing_message="Processing your request…",
            internal_action="Queue audit events for async write; block if critical audit",
        ),
        ErrorSpec(
            code="SAFETY_PERMISSION_ESCALATION",
            category="SAFETY", severity=10, is_retryable=False, is_recoverable=False,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=0, recovery_timeout_ms=1000,
            user_facing_message="Security check — operation not permitted.",
            internal_action="Reject immediately; alert security team; quarantine session",
        ),
        ErrorSpec(
            code="SAFETY_INPUT_INJECTION_DETECTED",
            category="SAFETY", severity=9, is_retryable=False, is_recoverable=True,
            recovery_strategy="graceful_degrade",
            max_recovery_attempts=1, recovery_timeout_ms=2000,
            user_facing_message="Input sanitised — processing safely…",
            internal_action="Sanitise input; re-run with cleaned prompt; log attack attempt",
        ),
    ])

    return {s.code: s for s in specs}


ERROR_REGISTRY: dict[str, ErrorSpec] = _build_registry()


# ---------------------------------------------------------------------------
# ErrorTaxonomy — high-level lookup & classification helpers
# ---------------------------------------------------------------------------

class ErrorTaxonomy:
    """Convenience façade over :data:`ERROR_REGISTRY`.

    Provides lookup-by-code, lookup-by-category, severity filtering,
    and heuristic classification from raw exceptions.
    """

    def __init__(self, registry: Optional[dict[str, ErrorSpec]] = None) -> None:
        self._registry = registry or ERROR_REGISTRY

    # -- lookup -----------------------------------------------------------

    def get(self, code: str) -> Optional[ErrorSpec]:
        """Return the :class:`ErrorSpec` for *code*, or ``None``."""
        return self._registry.get(code)

    def by_category(self, category: str) -> list[ErrorSpec]:
        """Return all errors in *category*."""
        return [s for s in self._registry.values() if s.category == category]

    def retryable(self) -> list[ErrorSpec]:
        """Return all retryable error specs."""
        return [s for s in self._registry.values() if s.is_retryable]

    def by_severity(self, min_severity: int = 1, max_severity: int = 10) -> list[ErrorSpec]:
        """Return errors within severity range (inclusive)."""
        return [
            s for s in self._registry.values()
            if min_severity <= s.severity <= max_severity
        ]

    def by_strategy(self, strategy: str) -> list[ErrorSpec]:
        """Return all errors that use *strategy* as primary recovery."""
        return [s for s in self._registry.values() if s.recovery_strategy == strategy]

    @property
    def all_codes(self) -> list[str]:
        """Sorted list of all error codes."""
        return sorted(self._registry.keys())

    @property
    def categories(self) -> list[str]:
        """Distinct categories present in the registry."""
        return sorted({s.category for s in self._registry.values()})

    def __len__(self) -> int:
        return len(self._registry)

    # -- heuristic classification from exceptions -------------------------

    _HEURISTICS: list[tuple[str, list[str]]] = [
        ("MODEL_RATE_LIMIT_SOFT", ["rate limit", "429", "too many requests"]),
        ("MODEL_RATE_LIMIT_HARD", ["rate limit exceeded", "quota"]),
        ("NETWORK_TIMEOUT_CONNECT", ["connect timeout", "connection timed out"]),
        ("NETWORK_TIMEOUT_READ", ["read timeout", "read timed out"]),
        ("NETWORK_CONNECTION_REFUSED", ["connection refused", "econnrefused"]),
        ("NETWORK_DNS_RESOLUTION", ["dns", "name resolution", "getaddrinfo"]),
        ("NETWORK_SSL_CERTIFICATE", ["ssl", "certificate"]),
        ("NETWORK_HOST_UNREACHABLE", ["host unreachable", "no route"]),
        ("MODEL_CONTEXT_WINDOW_EXCEEDED", ["context length", "context window", "maximum context"]),
        ("MODEL_OVERLOADED", ["overloaded", "503", "service unavailable"]),
        ("MODEL_UNAVAILABLE", ["model not found", "model unavailable", "404"]),
        ("MODEL_INVALID_API_KEY", ["unauthorized", "invalid api key", "401", "403"]),
        ("EXECUTION_TOOL_TIMEOUT", ["tool timeout", "execution timeout"]),
        ("EXECUTION_SANDBOX_CRASH", ["sandbox", "container crash"]),
        ("CONTENT_MALFORMED_JSON", ["json", "decode error", "unexpected token"]),
        ("CONTENT_EMPTY_RESPONSE", ["empty response", "no content"]),
        ("STREAMING_SSE_DISCONNECTED", ["sse", "event stream", "stream disconnected"]),
        ("STREAMING_WEBSOCKET_CLOSED", ["websocket closed", "ws closed"]),
        ("SAFETY_FILTER_TRIGGERED", ["safety", "content policy", "content filter"]),
    ]

    def classify_exception(self, exc: Exception) -> ErrorSpec:
        """Best-effort classification of an arbitrary exception.

        Falls back to ``NETWORK_CONNECTION_REFUSED`` if nothing matches —
        always returns a valid :class:`ErrorSpec`.
        """
        msg = str(exc).lower()
        status_code = getattr(exc, "status_code", None) or getattr(exc, "status", None)
        if status_code is not None:
            msg += f" {status_code}"

        for code, patterns in self._HEURISTICS:
            for pat in patterns:
                if pat in msg:
                    spec = self._registry.get(code)
                    if spec:
                        return spec
                    break

        # Fallback to a generic retryable network error
        return self._registry["NETWORK_CONNECTION_REFUSED"]
