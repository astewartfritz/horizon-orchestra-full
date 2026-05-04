"""Horizon Orchestra — Usage Tracking Middleware.

Intercepts agent execution events to track and meter all billable
usage.  Plugs into the agent loop as a companion to SecurityMiddleware,
and into SpeechProvider as a wrapper.

Responsibilities:
1. Count LLM tokens per model (input/output from API responses)
2. Count tool executions by type
3. Track STT duration and TTS character counts
4. Enforce tier limits (reject over-limit actions)
5. Report usage to BillingManager (which sends to Stripe meters)
6. Provide real-time usage dashboards

Usage::

    from orchestra.usage_tracker import UsageTracker
    from orchestra.stripe_billing import BillingManager, PricingTier

    billing = BillingManager()
    tracker = UsageTracker(
        billing=billing,
        customer_id="cus_abc123",
        tier=PricingTier.BUILDER,
    )

    # Wire into agent config
    config = AgentConfig(model="gemma-4-31b", usage_tracker=tracker)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "UsageTracker",
    "NullUsageTracker",
    "UsageBudget",
    "UsageSnapshot",
    "TIER_LIMITS",
]

log = logging.getLogger("orchestra.usage_tracker")


# ---------------------------------------------------------------------------
# Tier limit definitions
# ---------------------------------------------------------------------------

TIER_LIMITS: dict[str, dict[str, Any]] = {
    "maker": {
        "allowed_models": {
            "gemma-4-e4b", "gemma-4-e2b",
            "gemma-4-ollama", "gemma-4-26b-ollama", "ollama-local",
        },
        "allowed_stt": {"whisper_local"},
        "allowed_tts": {"kokoro", "chatterbox"},
        "allowed_architectures": {"A"},
        "allowed_security": {"standard", "permissive"},
        "max_tool_calls_monthly": 1000,
        "max_sessions_daily": 10,
        "max_swarm_agents": 0,
        "included_stt_seconds": 3600,        # 60 min
        "included_tts_seconds": 1800,         # 30 min
        "included_model_credit_cents": 0,
        "max_memory_entries": 100,
        "enable_domain_router": False,
        "enable_voice_cloning": False,
    },
    "builder": {
        "allowed_models": {
            "gemma-4-31b", "gemma-4-26b-moe", "gemma-4-e4b", "gemma-4-e2b",
            "gemma-4-31b-local", "gemma-4-ollama", "gemma-4-26b-ollama",
            "kimi-k2.5", "kimi-k2.5-openrouter", "kimi-k2.5-together", "kimi-k2.5-local",
            "sonar", "grok-3", "ollama-local",
        },
        "allowed_stt": {"whisper_api", "deepgram", "groq_whisper", "whisper_local"},
        "allowed_tts": {"openai_tts", "kokoro", "fish_speech", "chatterbox"},
        "allowed_architectures": {"A", "C"},
        "allowed_security": {"standard", "strict", "permissive"},
        "max_tool_calls_monthly": 50000,
        "max_sessions_daily": 100,
        "max_swarm_agents": 5,
        "included_stt_seconds": 36000,        # 600 min
        "included_tts_seconds": 7200,          # 120 min
        "included_model_credit_cents": 1000,   # $10
        "max_memory_entries": 5000,
        "enable_domain_router": False,
        "enable_voice_cloning": False,
    },
    "pro": {
        "allowed_models": None,     # None = all models
        "allowed_stt": None,        # None = all backends
        "allowed_tts": None,
        "allowed_architectures": {"A", "C", "E"},
        "allowed_security": None,   # all policies
        "max_tool_calls_monthly": 500000,
        "max_sessions_daily": 0,    # 0 = unlimited
        "max_swarm_agents": 100,
        "included_stt_seconds": 360000,        # 6000 min
        "included_tts_seconds": 72000,          # 1200 min
        "included_model_credit_cents": 5000,    # $50
        "max_memory_entries": 50000,
        "enable_domain_router": True,
        "enable_voice_cloning": True,
    },
    "enterprise": {
        "allowed_models": None,
        "allowed_stt": None,
        "allowed_tts": None,
        "allowed_architectures": None,   # all including custom
        "allowed_security": None,
        "max_tool_calls_monthly": 0,     # 0 = unlimited
        "max_sessions_daily": 0,
        "max_swarm_agents": 0,           # 0 = unlimited
        "included_stt_seconds": 0,       # 0 = unlimited
        "included_tts_seconds": 0,
        "included_model_credit_cents": 20000,  # $200
        "max_memory_entries": 0,
        "enable_domain_router": True,
        "enable_voice_cloning": True,
    },
}

# Models for which "0" swarm agents means unlimited (enterprise/pro context)
_UNLIMITED_TIERS = {"enterprise"}

# Characters-per-second estimate for TTS duration calculation
_TTS_CHARS_PER_SECOND = 150.0

# ---------------------------------------------------------------------------
# Per-model cost table  ($ per 1 M tokens; mirrors router.py DEFAULT_MODELS)
# ---------------------------------------------------------------------------

# Keyed on the *normalised* model key (see _normalize_model_key below).
# Values are (input_cents_per_1k, output_cents_per_1k) i.e. cents per 1 000 tokens.
_MODEL_COSTS: dict[str, tuple[float, float]] = {
    # Kimi K2.5
    "kimi-k2.5":           (0.060, 0.250),   # $0.60 / $2.50 per 1M
    # Gemma 4 cloud
    "gemma-4-31b":         (0.030, 0.120),   # estimated
    "gemma-4-26b-moe":     (0.020, 0.080),
    "gemma-4-e4b":         (0.005, 0.020),
    "gemma-4-e2b":         (0.003, 0.010),
    # Gemma 4 local / Ollama — effectively free but track tokens
    "gemma-4-31b-local":   (0.0,   0.0),
    "gemma-4-26b-ollama":  (0.0,   0.0),
    "gemma-4-ollama":      (0.0,   0.0),
    "ollama-local":        (0.0,   0.0),
    # Sonar / Perplexity
    "sonar":               (0.100, 0.100),   # $1/1M
    # Grok
    "grok-3":              (0.300, 1.500),
    # Claude (not in TIER_LIMITS maker/builder but present in pro/enterprise)
    "claude-opus-4.6":     (1.500, 7.500),
    "claude-sonnet-4.6":   (0.300, 1.500),
    "claude-haiku-4.5":    (0.025, 0.125),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _normalize_model_key(model: str) -> str:
    """Strip provider suffixes to get a canonical cost-lookup key.

    Examples::

        "gemma-4-31b-openrouter" -> "gemma-4-31b"
        "kimi-k2.5-together"     -> "kimi-k2.5"
        "claude-opus-4.6-native" -> "claude-opus-4.6"
    """
    for suffix in ("-openrouter", "-together", "-native", "-local"):
        if model.endswith(suffix):
            return model[: -len(suffix)]
    return model


def _estimate_tts_duration(char_count: int) -> float:
    """Estimate TTS playback duration in seconds from character count."""
    return char_count / _TTS_CHARS_PER_SECOND


def _is_unlimited(tier: str, key: str) -> bool:
    """Return True if the limit value of 0 means unlimited for this tier/key."""
    # For enterprise tier, 0 on all *count* limits means unlimited.
    # model_credit_cents is always finite (real API money).
    if tier == "enterprise" and key != "included_model_credit_cents":
        return True
    # For non-enterprise tiers, 0 on daily sessions / swarm agents also means unlimited.
    if key in ("max_sessions_daily", "max_swarm_agents") and tier in ("pro",):
        return True
    return False


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class UsageBudget:
    """Remaining budget for a customer in the current billing period."""
    tool_calls_remaining: int
    sessions_remaining_today: int
    swarm_agents_remaining: int
    stt_seconds_remaining: float
    tts_characters_remaining: float   # derived from tts_seconds_remaining * chars/sec
    memory_entries_remaining: int
    model_credit_remaining_cents: int

    @property
    def has_tool_budget(self) -> bool:
        """True when the customer can still execute tools."""
        return self.tool_calls_remaining > 0

    @property
    def has_stt_budget(self) -> bool:
        """True when the customer has STT seconds remaining."""
        return self.stt_seconds_remaining > 0

    @property
    def has_tts_budget(self) -> bool:
        """True when the customer has TTS character budget remaining."""
        return self.tts_characters_remaining > 0


@dataclass
class UsageSnapshot:
    """Current usage totals for a customer."""
    period_start: float          # unix timestamp of the billing period start
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    llm_cost_cents: int = 0      # integer cents
    tool_calls: int = 0
    swarm_spawns: int = 0
    stt_seconds: float = 0.0
    tts_characters: int = 0
    memory_entries: int = 0
    code_executions: int = 0
    browser_actions: int = 0
    sessions_today: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize snapshot to a plain dictionary."""
        return {
            "period_start": self.period_start,
            "llm_input_tokens": self.llm_input_tokens,
            "llm_output_tokens": self.llm_output_tokens,
            "llm_cost_cents": self.llm_cost_cents,
            "tool_calls": self.tool_calls,
            "swarm_spawns": self.swarm_spawns,
            "stt_seconds": self.stt_seconds,
            "tts_characters": self.tts_characters,
            "memory_entries": self.memory_entries,
            "code_executions": self.code_executions,
            "browser_actions": self.browser_actions,
            "sessions_today": self.sessions_today,
        }


# ---------------------------------------------------------------------------
# UsageTracker
# ---------------------------------------------------------------------------

class UsageTracker:
    """Tracks and meters all billable usage for a customer.

    Acts as middleware in the agent execution pipeline.  All counter
    mutations are protected by an asyncio.Lock so the tracker is safe
    to use from concurrent coroutines (e.g. parallel swarm agents).

    Parameters
    ----------
    billing:
        An optional BillingManager instance.  When provided, usage is
        flushed to Stripe metered billing after each tracked event.
        Pass ``None`` to run in local-only mode.
    customer_id:
        The Stripe customer ID (``cus_…``).  Required when ``billing``
        is provided.
    tier:
        Pricing tier name.  Must be one of ``"maker"``, ``"builder"``,
        ``"pro"``, ``"enterprise"``.  Defaults to ``"maker"``.
    enforce_limits:
        When ``True`` (the default), the tracker rejects actions that
        would exceed the customer's tier limits by returning
        ``(False, reason)``.  Set to ``False`` to track without
        blocking.
    """

    def __init__(
        self,
        billing: Any = None,
        customer_id: str = "",
        tier: str = "maker",
        enforce_limits: bool = True,
    ) -> None:
        self._billing = billing
        self._customer_id = customer_id
        self._tier = tier.lower() if tier else "maker"
        self._enforce = enforce_limits
        self._limits = TIER_LIMITS.get(self._tier, TIER_LIMITS["maker"])
        self._lock = asyncio.Lock()

        # Active swarm agents (for concurrent-limit checking)
        self._active_swarm_agents: set[str] = set()

        # In-memory usage snapshot
        self._snapshot = UsageSnapshot(period_start=time.time())

        log.debug(
            "UsageTracker initialised: customer=%s tier=%s enforce=%s",
            customer_id or "(local)", self._tier, enforce_limits,
        )

    # ── Internal helpers ──────────────────────────────────────────────────

    def _limit(self, key: str) -> int | float | set | None:
        """Convenience accessor for a tier-limit value."""
        return self._limits.get(key)

    def _is_unlimited_limit(self, key: str) -> bool:
        """Return True when a zero-valued limit means unlimited for this tier."""
        return _is_unlimited(self._tier, key)

    def _compute_llm_cost_cents(self, model: str, input_tokens: int, output_tokens: int) -> int:
        """Return the integer cent cost for a model call."""
        key = _normalize_model_key(model)
        cost_pair = _MODEL_COSTS.get(key)
        if cost_pair is None:
            # Unknown model — fall back to a conservative estimate
            log.debug("Unknown model cost for %r; using fallback pricing", model)
            cost_pair = (0.100, 0.500)   # $1/$5 per 1M — safe over-estimate
        input_cost_cents = (input_tokens / 1000.0) * cost_pair[0]
        output_cost_cents = (output_tokens / 1000.0) * cost_pair[1]
        return max(0, int((input_cost_cents + output_cost_cents) + 0.5))  # round-half-up

    async def _flush_to_billing(self, event_type: str, quantity: float, metadata: dict | None = None) -> None:
        """Report a usage event to the BillingManager if configured."""
        if self._billing is None or not self._customer_id:
            return
        try:
            await self._billing.record_usage(
                customer_id=self._customer_id,
                event_type=event_type,
                quantity=quantity,
                metadata=metadata or {},
            )
        except Exception as exc:
            log.warning("Failed to flush usage to billing (%s): %s", event_type, exc)

    # ── Token Tracking ────────────────────────────────────────────────────

    async def track_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[bool, str]:
        """Record an LLM call.  Returns (allowed, reason).

        Checks model access for tier, calculates cost, applies to
        model-credit balance, records overage when credit is exhausted.
        """
        # Access check
        allowed, reason = self.check_model(model)
        if not allowed:
            return False, reason

        cost_cents = self._compute_llm_cost_cents(model, input_tokens, output_tokens)

        async with self._lock:
            self._snapshot.llm_input_tokens += input_tokens
            self._snapshot.llm_output_tokens += output_tokens
            self._snapshot.llm_cost_cents += cost_cents

        log.debug(
            "LLM call tracked: model=%s in=%d out=%d cost=%d¢",
            model, input_tokens, output_tokens, cost_cents,
        )

        # Flush to billing
        await self._flush_to_billing(
            "llm_tokens",
            input_tokens + output_tokens,
            {"model": model, "input_tokens": input_tokens,
             "output_tokens": output_tokens, "cost_cents": cost_cents},
        )
        return True, ""

    # ── Tool Tracking ─────────────────────────────────────────────────────

    async def track_tool_call(
        self,
        tool_name: str,
    ) -> tuple[bool, str]:
        """Record a tool execution.  Returns (allowed, reason).

        Enforces the monthly tool-call limit for the tier.  Applies
        special counters for ``execute_code`` and ``browser_action``.
        """
        max_tools: int = self._limits.get("max_tool_calls_monthly", 0)
        is_unlimited = max_tools == 0 and self._is_unlimited_limit("max_tool_calls_monthly")

        if self._enforce and not is_unlimited and max_tools > 0:
            async with self._lock:
                current = self._snapshot.tool_calls
            if current >= max_tools:
                reason = (
                    f"Monthly tool call limit reached ({max_tools}). "
                    f"Upgrade your plan to continue."
                )
                log.warning("Tool call blocked for %s: %s", self._customer_id or "local", reason)
                return False, reason

        async with self._lock:
            self._snapshot.tool_calls += 1
            if tool_name in ("execute_code", "code_execution"):
                self._snapshot.code_executions += 1
            elif tool_name in ("browser_action", "browser_navigate", "browser_click"):
                self._snapshot.browser_actions += 1

        log.debug("Tool call tracked: %s", tool_name)

        await self._flush_to_billing(
            "tool_call",
            1,
            {"tool_name": tool_name},
        )
        return True, ""

    # ── Swarm Tracking ────────────────────────────────────────────────────

    async def track_swarm_spawn(
        self,
        agent_id: str,
        model: str,
    ) -> tuple[bool, str]:
        """Record a sub-agent spawn.  Returns (allowed, reason).

        Checks the concurrent swarm-agent limit for the tier.  Call
        ``track_swarm_done(agent_id)`` when the sub-agent finishes so
        that the slot is freed.
        """
        max_agents: int = self._limits.get("max_swarm_agents", 0)
        is_unlimited = max_agents == 0 and self._is_unlimited_limit("max_swarm_agents")

        if max_agents == 0 and not is_unlimited:
            # Swarm not available on this tier
            return False, (
                f"Swarm agents are not available on the '{self._tier}' tier. "
                "Upgrade to Builder or higher."
            )

        if self._enforce and not is_unlimited:
            async with self._lock:
                active = len(self._active_swarm_agents)
            if active >= max_agents:
                return False, (
                    f"Concurrent swarm agent limit reached ({max_agents}). "
                    "Wait for active agents to finish or upgrade your plan."
                )

        # Also check model access for the sub-agent
        model_allowed, model_reason = self.check_model(model)
        if not model_allowed:
            return False, model_reason

        async with self._lock:
            self._active_swarm_agents.add(agent_id)
            self._snapshot.swarm_spawns += 1

        log.debug("Swarm spawn tracked: agent_id=%s model=%s", agent_id, model)

        await self._flush_to_billing(
            "swarm_spawn",
            1,
            {"agent_id": agent_id, "model": model},
        )
        return True, ""

    async def track_swarm_done(self, agent_id: str) -> None:
        """Release the swarm slot when a sub-agent finishes."""
        async with self._lock:
            self._active_swarm_agents.discard(agent_id)
        log.debug("Swarm agent released: agent_id=%s", agent_id)

    # ── Speech Tracking ───────────────────────────────────────────────────

    async def track_stt(
        self,
        duration_seconds: float,
        backend: str,
    ) -> tuple[bool, str]:
        """Record an STT transcription.  Returns (allowed, reason).

        Checks backend access and remaining STT minute budget for the tier.
        """
        # Backend access check
        allowed_stt: set | None = self._limits.get("allowed_stt")
        if self._enforce and allowed_stt is not None and backend not in allowed_stt:
            return False, (
                f"STT backend '{backend}' is not available on the '{self._tier}' tier. "
                f"Available: {sorted(allowed_stt)}."
            )

        # Seconds budget check
        included_stt: float = self._limits.get("included_stt_seconds", 0)
        is_unlimited = included_stt == 0 and self._is_unlimited_limit("included_stt_seconds")

        if self._enforce and not is_unlimited and included_stt > 0:
            async with self._lock:
                current = self._snapshot.stt_seconds
            if current + duration_seconds > included_stt:
                remaining = max(0.0, included_stt - current)
                return False, (
                    f"STT budget exhausted. "
                    f"{remaining:.0f}s remaining of {included_stt:.0f}s included. "
                    "Upgrade your plan for more STT minutes."
                )

        async with self._lock:
            self._snapshot.stt_seconds += duration_seconds

        log.debug("STT tracked: %.1fs via %s", duration_seconds, backend)

        await self._flush_to_billing(
            "stt_seconds",
            duration_seconds,
            {"backend": backend, "duration_seconds": duration_seconds},
        )
        return True, ""

    async def track_tts(
        self,
        text_length: int,
        backend: str,
    ) -> tuple[bool, str]:
        """Record a TTS synthesis.  Returns (allowed, reason).

        Checks backend access and remaining TTS character budget for the tier.
        The character budget is derived from ``included_tts_seconds`` at the
        ``_TTS_CHARS_PER_SECOND`` estimate.
        """
        # Backend access check
        allowed_tts: set | None = self._limits.get("allowed_tts")
        if self._enforce and allowed_tts is not None and backend not in allowed_tts:
            return False, (
                f"TTS backend '{backend}' is not available on the '{self._tier}' tier. "
                f"Available: {sorted(allowed_tts)}."
            )

        # Character budget derived from tts_seconds
        included_tts_secs: float = self._limits.get("included_tts_seconds", 0)
        is_unlimited = included_tts_secs == 0 and self._is_unlimited_limit("included_tts_seconds")
        included_chars = int(included_tts_secs * _TTS_CHARS_PER_SECOND)

        if self._enforce and not is_unlimited and included_chars > 0:
            async with self._lock:
                current_chars = self._snapshot.tts_characters
            if current_chars + text_length > included_chars:
                remaining = max(0, included_chars - current_chars)
                return False, (
                    f"TTS budget exhausted. "
                    f"{remaining} characters remaining of ~{included_chars} included. "
                    "Upgrade your plan for more TTS capacity."
                )

        async with self._lock:
            self._snapshot.tts_characters += text_length

        estimated_seconds = _estimate_tts_duration(text_length)
        log.debug("TTS tracked: %d chars (~%.1fs) via %s", text_length, estimated_seconds, backend)

        await self._flush_to_billing(
            "tts_characters",
            text_length,
            {"backend": backend, "text_length": text_length,
             "estimated_seconds": estimated_seconds},
        )
        return True, ""

    # ── Memory Tracking ───────────────────────────────────────────────────

    async def track_memory_write(self) -> tuple[bool, str]:
        """Record a memory entry creation."""
        max_entries: int = self._limits.get("max_memory_entries", 0)
        is_unlimited = max_entries == 0 and self._is_unlimited_limit("max_memory_entries")

        if self._enforce and not is_unlimited and max_entries > 0:
            async with self._lock:
                current = self._snapshot.memory_entries
            if current >= max_entries:
                return False, (
                    f"Memory limit reached ({max_entries} entries). "
                    "Upgrade your plan for more memory storage."
                )

        async with self._lock:
            self._snapshot.memory_entries += 1

        log.debug("Memory write tracked (total: %d)", self._snapshot.memory_entries)

        await self._flush_to_billing("memory_write", 1, {})
        return True, ""

    # ── Session Tracking ──────────────────────────────────────────────────

    async def start_session(self) -> tuple[bool, str]:
        """Record a new agent session start.  Checks daily limit."""
        max_sessions: int = self._limits.get("max_sessions_daily", 0)
        is_unlimited = max_sessions == 0 and self._is_unlimited_limit("max_sessions_daily")

        if self._enforce and not is_unlimited and max_sessions > 0:
            async with self._lock:
                current = self._snapshot.sessions_today
            if current >= max_sessions:
                return False, (
                    f"Daily session limit reached ({max_sessions} sessions/day). "
                    "Upgrade your plan for more sessions."
                )

        async with self._lock:
            self._snapshot.sessions_today += 1

        log.debug("Session started (today: %d)", self._snapshot.sessions_today)

        await self._flush_to_billing("session_start", 1, {})
        return True, ""

    # ── Architecture / Model / Feature Checks ─────────────────────────────

    def check_architecture(self, arch: str) -> tuple[bool, str]:
        """Check if the customer's tier allows this execution architecture.

        Parameters
        ----------
        arch:
            Architecture identifier, e.g. ``"A"``, ``"C"``, ``"E"``.
        """
        allowed: set | None = self._limits.get("allowed_architectures")
        if allowed is None:
            return True, ""  # unlimited tier
        if arch in allowed:
            return True, ""
        return False, (
            f"Architecture '{arch}' is not available on the '{self._tier}' tier. "
            f"Available: {sorted(allowed)}."
        )

    def check_model(self, model: str) -> tuple[bool, str]:
        """Check if the customer's tier allows this model.

        Normalises provider-suffixed model names before checking.
        """
        allowed: set | None = self._limits.get("allowed_models")
        if allowed is None:
            return True, ""  # unlimited tier (pro / enterprise)

        # Check both the raw name and the normalised key
        key = _normalize_model_key(model)
        if model in allowed or key in allowed:
            return True, ""

        return False, (
            f"Model '{model}' is not available on the '{self._tier}' tier. "
            "Upgrade your plan to access this model."
        )

    def check_feature(self, feature: str) -> tuple[bool, str]:
        """Check if the customer's tier allows a named feature.

        Recognised feature names:

        - ``"domain_router"`` — intelligent task-to-model routing
        - ``"voice_cloning"`` — ElevenLabs / Fish Speech zero-shot cloning
        - ``"safety_critical"`` — safety-critical security policy
        - ``"architecture_e"`` — Production orchestrator (arch E)
        """
        feature_key_map = {
            "domain_router":   "enable_domain_router",
            "voice_cloning":   "enable_voice_cloning",
        }

        # Map feature to a tier-limit key when possible
        limit_key = feature_key_map.get(feature)
        if limit_key is not None:
            enabled: bool = bool(self._limits.get(limit_key, False))
            if enabled:
                return True, ""
            return False, (
                f"Feature '{feature}' is not available on the '{self._tier}' tier. "
                "Upgrade to Pro or Enterprise."
            )

        # Architecture-E check
        if feature == "architecture_e":
            return self.check_architecture("E")

        # Safety-critical security policy check
        if feature == "safety_critical":
            allowed_sec: set | None = self._limits.get("allowed_security")
            if allowed_sec is None or "safety_critical" in allowed_sec:
                return True, ""
            return False, (
                f"Safety-critical security policy is not available on the '{self._tier}' tier."
            )

        # Unknown feature — allow by default to avoid false-positive blocks
        log.debug("Unknown feature check: %r — allowing by default", feature)
        return True, ""

    # ── Budget / Dashboard ────────────────────────────────────────────────

    def get_budget(self) -> UsageBudget:
        """Return remaining budget for current period."""
        snap = self._snapshot
        limits = self._limits

        # Tool calls
        max_tools: int = limits.get("max_tool_calls_monthly", 0)
        if max_tools == 0 and self._is_unlimited_limit("max_tool_calls_monthly"):
            tools_remaining = 2 ** 31  # sentinel for "unlimited"
        elif max_tools == 0:
            tools_remaining = 0
        else:
            tools_remaining = max(0, max_tools - snap.tool_calls)

        # Sessions today
        max_sess: int = limits.get("max_sessions_daily", 0)
        if max_sess == 0 and self._is_unlimited_limit("max_sessions_daily"):
            sess_remaining = 2 ** 31
        elif max_sess == 0:
            sess_remaining = 0
        else:
            sess_remaining = max(0, max_sess - snap.sessions_today)

        # Swarm agents (concurrent slots)
        max_swarm: int = limits.get("max_swarm_agents", 0)
        if max_swarm == 0 and self._is_unlimited_limit("max_swarm_agents"):
            swarm_remaining = 2 ** 31
        elif max_swarm == 0:
            swarm_remaining = 0
        else:
            swarm_remaining = max(0, max_swarm - len(self._active_swarm_agents))

        # STT seconds
        included_stt: float = limits.get("included_stt_seconds", 0)
        if included_stt == 0 and self._is_unlimited_limit("included_stt_seconds"):
            stt_remaining: float = float(2 ** 31)
        else:
            stt_remaining = max(0.0, included_stt - snap.stt_seconds)

        # TTS characters (derived from tts_seconds)
        included_tts_secs: float = limits.get("included_tts_seconds", 0)
        if included_tts_secs == 0 and self._is_unlimited_limit("included_tts_seconds"):
            tts_chars_remaining: float = float(2 ** 31)
        else:
            included_tts_chars = included_tts_secs * _TTS_CHARS_PER_SECOND
            tts_chars_remaining = max(0.0, included_tts_chars - snap.tts_characters)

        # Memory entries
        max_mem: int = limits.get("max_memory_entries", 0)
        if max_mem == 0 and self._is_unlimited_limit("max_memory_entries"):
            mem_remaining = 2 ** 31
        elif max_mem == 0:
            mem_remaining = 0
        else:
            mem_remaining = max(0, max_mem - snap.memory_entries)

        # Model credit
        included_credit: int = limits.get("included_model_credit_cents", 0)
        credit_remaining = max(0, included_credit - snap.llm_cost_cents)

        return UsageBudget(
            tool_calls_remaining=tools_remaining,
            sessions_remaining_today=sess_remaining,
            swarm_agents_remaining=swarm_remaining,
            stt_seconds_remaining=stt_remaining,
            tts_characters_remaining=tts_chars_remaining,
            memory_entries_remaining=mem_remaining,
            model_credit_remaining_cents=credit_remaining,
        )

    def get_snapshot(self) -> UsageSnapshot:
        """Return a copy of the current usage totals."""
        snap = self._snapshot
        return UsageSnapshot(
            period_start=snap.period_start,
            llm_input_tokens=snap.llm_input_tokens,
            llm_output_tokens=snap.llm_output_tokens,
            llm_cost_cents=snap.llm_cost_cents,
            tool_calls=snap.tool_calls,
            swarm_spawns=snap.swarm_spawns,
            stt_seconds=snap.stt_seconds,
            tts_characters=snap.tts_characters,
            memory_entries=snap.memory_entries,
            code_executions=snap.code_executions,
            browser_actions=snap.browser_actions,
            sessions_today=snap.sessions_today,
        )

    def get_cost_breakdown(self) -> dict[str, Any]:
        """Return a detailed cost breakdown by category."""
        snap = self._snapshot
        limits = self._limits

        # Estimate per-category costs in cents
        stt_cost_cents = 0   # local or free backends assumed; override if cloud is tracked
        tts_cost_cents = 0   # same

        included_credit = limits.get("included_model_credit_cents", 0)
        overage_model_cents = max(0, snap.llm_cost_cents - included_credit)

        return {
            "period_start": snap.period_start,
            "tier": self._tier,
            "llm": {
                "input_tokens": snap.llm_input_tokens,
                "output_tokens": snap.llm_output_tokens,
                "cost_cents": snap.llm_cost_cents,
                "included_credit_cents": included_credit,
                "overage_cents": overage_model_cents,
            },
            "tools": {
                "total_calls": snap.tool_calls,
                "code_executions": snap.code_executions,
                "browser_actions": snap.browser_actions,
            },
            "swarm": {
                "total_spawns": snap.swarm_spawns,
                "active_now": len(self._active_swarm_agents),
            },
            "stt": {
                "seconds_used": snap.stt_seconds,
                "seconds_included": limits.get("included_stt_seconds", 0),
                "cost_cents": stt_cost_cents,
            },
            "tts": {
                "characters_used": snap.tts_characters,
                "characters_included": int(
                    limits.get("included_tts_seconds", 0) * _TTS_CHARS_PER_SECOND
                ),
                "cost_cents": tts_cost_cents,
            },
            "memory": {
                "entries_used": snap.memory_entries,
                "entries_limit": limits.get("max_memory_entries", 0),
            },
            "sessions": {
                "today": snap.sessions_today,
                "daily_limit": limits.get("max_sessions_daily", 0),
            },
            "total_estimated_cost_cents": snap.llm_cost_cents + stt_cost_cents + tts_cost_cents,
        }

    def reset_period(self) -> None:
        """Reset all usage counters for a new billing period.

        This should be called by the BillingManager at the start of
        each calendar month (or when the Stripe billing period rolls).
        Session-today counter is also reset as a convenience.
        """
        log.info("Resetting usage period for customer %s", self._customer_id or "(local)")
        self._snapshot = UsageSnapshot(period_start=time.time())
        # Note: active swarm agents are NOT reset — they reflect live state.

    @property
    def stats(self) -> dict[str, Any]:
        """Return a concise usage stats dict suitable for API responses."""
        snap = self._snapshot
        budget = self.get_budget()
        return {
            "customer_id": self._customer_id,
            "tier": self._tier,
            "period_start": snap.period_start,
            "llm_tokens_used": snap.llm_input_tokens + snap.llm_output_tokens,
            "llm_cost_cents": snap.llm_cost_cents,
            "tool_calls_used": snap.tool_calls,
            "tool_calls_remaining": budget.tool_calls_remaining,
            "stt_seconds_used": round(snap.stt_seconds, 1),
            "stt_seconds_remaining": round(budget.stt_seconds_remaining, 1),
            "tts_characters_used": snap.tts_characters,
            "tts_characters_remaining": budget.tts_characters_remaining,
            "memory_entries_used": snap.memory_entries,
            "memory_entries_remaining": budget.memory_entries_remaining,
            "sessions_today": snap.sessions_today,
            "sessions_remaining_today": budget.sessions_remaining_today,
            "swarm_spawns_total": snap.swarm_spawns,
            "swarm_agents_active": len(self._active_swarm_agents),
            "model_credit_remaining_cents": budget.model_credit_remaining_cents,
        }

    # ── Dunder ────────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"UsageTracker("
            f"customer_id={self._customer_id!r}, "
            f"tier={self._tier!r}, "
            f"enforce={self._enforce})"
        )


# ---------------------------------------------------------------------------
# NullUsageTracker — no-op implementation
# ---------------------------------------------------------------------------

class NullUsageTracker:
    """No-op usage tracker for when billing is disabled.

    All ``check_*`` methods return ``(True, "")``.
    All ``track_*`` methods are no-ops that return ``(True, "")``.
    Allows Orchestra to run without any billing configuration.

    The interface is identical to :class:`UsageTracker` so callers can
    substitute either without changing their code.
    """

    # ── Token Tracking ────────────────────────────────────────────────────

    async def track_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> tuple[bool, str]:
        return True, ""

    # ── Tool Tracking ─────────────────────────────────────────────────────

    async def track_tool_call(
        self,
        tool_name: str,
    ) -> tuple[bool, str]:
        return True, ""

    # ── Swarm Tracking ────────────────────────────────────────────────────

    async def track_swarm_spawn(
        self,
        agent_id: str,
        model: str,
    ) -> tuple[bool, str]:
        return True, ""

    async def track_swarm_done(self, agent_id: str) -> None:
        return

    # ── Speech Tracking ───────────────────────────────────────────────────

    async def track_stt(
        self,
        duration_seconds: float,
        backend: str,
    ) -> tuple[bool, str]:
        return True, ""

    async def track_tts(
        self,
        text_length: int,
        backend: str,
    ) -> tuple[bool, str]:
        return True, ""

    # ── Memory Tracking ───────────────────────────────────────────────────

    async def track_memory_write(self) -> tuple[bool, str]:
        return True, ""

    # ── Session Tracking ──────────────────────────────────────────────────

    async def start_session(self) -> tuple[bool, str]:
        return True, ""

    # ── Architecture / Model / Feature Checks ─────────────────────────────

    def check_architecture(self, arch: str) -> tuple[bool, str]:
        return True, ""

    def check_model(self, model: str) -> tuple[bool, str]:
        return True, ""

    def check_feature(self, feature: str) -> tuple[bool, str]:
        return True, ""

    # ── Budget / Dashboard ────────────────────────────────────────────────

    def get_budget(self) -> UsageBudget:
        _INF = 2 ** 31
        return UsageBudget(
            tool_calls_remaining=_INF,
            sessions_remaining_today=_INF,
            swarm_agents_remaining=_INF,
            stt_seconds_remaining=float(_INF),
            tts_characters_remaining=float(_INF),
            memory_entries_remaining=_INF,
            model_credit_remaining_cents=_INF,
        )

    def get_snapshot(self) -> UsageSnapshot:
        return UsageSnapshot(period_start=time.time())

    def get_cost_breakdown(self) -> dict[str, Any]:
        return {"note": "billing_disabled"}

    def reset_period(self) -> None:
        return

    @property
    def stats(self) -> dict[str, Any]:
        return {"billing": "disabled"}

    def __repr__(self) -> str:
        return "NullUsageTracker()"
