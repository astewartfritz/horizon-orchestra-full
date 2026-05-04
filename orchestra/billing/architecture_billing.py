"""Architecture-aware billing for Horizon Orchestra.

Maps each architecture (A–E) to its actual resource profile so that
Stripe metering, feature gating, and cost estimation reflect what the
user is *really* consuming rather than flat request counts.

Resource Profiles
-----------------
Each architecture consumes resources differently:

* **Architecture A** (Monolithic) — one agent loop, up to 300 sequential
  tool calls.  Moderate token throughput, no parallelism overhead.
* **Architecture B** (RAG Pipeline) — Sonar retrieval + Kimi synthesis.
  Cost scales with ``sources × citation_hops``.  Each multi-hop research
  run multiplies retrieval calls.
* **Architecture C** (Swarm) — up to 100 parallel sub-agents each with
  their own tool surface.  High concurrency: token and tool-call
  consumption scales with ``sub_agents × avg_calls_per_agent``.
* **Architecture D** (MCP Tool Hub) — many simultaneous MCP connections,
  tool calls fan out across servers.  Metering tracks connections,
  tool calls, and deterministic-wrapper invocations separately.
* **Architecture E** (Production) — wraps A/B/C/D + task-queue overhead.
  Adds background job metering to the underlying backend's profile.

Tier Feature Gating
-------------------
Not every tier unlocks every architecture:

* **Free**  — Architecture A only, basic limits.
* **Pro**   — A + B (RAG research).  Unlocks multi-hop.
* **Team**  — A + B + C (swarm).  Higher concurrency.
* **Max**   — A + B + C + D (full MCP hub) + E (production deployment).
  Long-horizon tasks, custom MCP servers, unlimited everything.

Usage:

    from orchestra.billing.architecture_billing import (
        ArchitectureBillingManager,
        check_architecture_access,
        estimate_cost,
    )

    mgr = ArchitectureBillingManager(billing)
    allowed = await mgr.check_access(user_id, architecture="C")
    cost = mgr.estimate_run_cost(architecture="C", sub_agents=8, tool_calls=120)
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

__all__ = [
    "Architecture",
    "ArchitectureProfile",
    "ArchitectureLimits",
    "ArchitectureMeter",
    "ArchitectureBillingManager",
    "CostEstimate",
    "ARCHITECTURE_PROFILES",
    "TIER_ARCHITECTURE_ACCESS",
    "TIER_ARCHITECTURE_LIMITS",
    "check_architecture_access",
    "estimate_cost",
]

logger = logging.getLogger("orchestra.billing.architecture")


# ---------------------------------------------------------------------------
# Architecture enum
# ---------------------------------------------------------------------------

class Architecture(str, Enum):
    """The five orchestration architectures."""
    A = "A"   # Monolithic Orchestrator
    B = "B"   # RAG Pipeline
    C = "C"   # Agent Swarm
    D = "D"   # MCP Tool Hub
    E = "E"   # Production Stack (wraps A-D)

    @classmethod
    def from_str(cls, value: str) -> "Architecture":
        """Parse a string like 'A', 'b', 'arch_c' into an Architecture."""
        cleaned = value.upper().strip().replace("ARCH_", "").replace("ARCH", "")
        try:
            return cls(cleaned)
        except ValueError:
            raise ValueError(
                f"Unknown architecture '{value}'. "
                f"Valid: {[a.value for a in cls]}"
            ) from None


# ---------------------------------------------------------------------------
# Architecture resource profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArchitectureProfile:
    """Static resource profile describing an architecture's cost shape."""

    name: str
    description: str

    # Cost multipliers relative to a single Arch-A request (= 1.0)
    base_cost_multiplier: float

    # Typical resource consumption per run
    avg_tool_calls_per_run: int
    avg_tokens_per_run: int
    avg_api_calls_per_run: int       # external API calls (Sonar, MCP, etc.)
    max_parallel_agents: int         # 1 for A/B, 100 for C, varies for D

    # Whether the architecture supports specific capabilities
    supports_multi_hop: bool = False
    supports_swarm: bool = False
    supports_mcp: bool = False
    supports_long_horizon: bool = True
    supports_streaming: bool = True
    supports_adaptive_context: bool = True


ARCHITECTURE_PROFILES: dict[Architecture, ArchitectureProfile] = {
    Architecture.A: ArchitectureProfile(
        name="Monolithic Orchestrator",
        description="Single Kimi K2.5 agent loop with full tool surface.",
        base_cost_multiplier=1.0,
        avg_tool_calls_per_run=15,
        avg_tokens_per_run=8_000,
        avg_api_calls_per_run=1,
        max_parallel_agents=1,
    ),
    Architecture.B: ArchitectureProfile(
        name="RAG Pipeline",
        description="Sonar retrieval → Kimi K2.5 Thinking synthesis.",
        base_cost_multiplier=2.5,
        avg_tool_calls_per_run=5,
        avg_tokens_per_run=20_000,
        avg_api_calls_per_run=8,        # query expansion + parallel Sonar calls
        max_parallel_agents=1,
        supports_multi_hop=True,
    ),
    Architecture.C: ArchitectureProfile(
        name="Agent Swarm",
        description="Kimi K2.5 native swarm: coordinator + parallel sub-agents.",
        base_cost_multiplier=5.0,
        avg_tool_calls_per_run=80,
        avg_tokens_per_run=60_000,
        avg_api_calls_per_run=12,
        max_parallel_agents=100,
        supports_swarm=True,
    ),
    Architecture.D: ArchitectureProfile(
        name="MCP Tool Hub",
        description="Dynamic tool discovery across MCP servers.",
        base_cost_multiplier=3.0,
        avg_tool_calls_per_run=25,
        avg_tokens_per_run=15_000,
        avg_api_calls_per_run=20,       # MCP tool calls fan out
        max_parallel_agents=1,
        supports_mcp=True,
    ),
    Architecture.E: ArchitectureProfile(
        name="Production Stack",
        description="Full production deployment wrapping A/B/C/D.",
        base_cost_multiplier=1.2,       # 20% overhead on top of wrapped arch
        avg_tool_calls_per_run=20,
        avg_tokens_per_run=12_000,
        avg_api_calls_per_run=5,
        max_parallel_agents=100,
        supports_multi_hop=True,
        supports_swarm=True,
        supports_mcp=True,
    ),
}


# ---------------------------------------------------------------------------
# Tier → Architecture access mapping
# ---------------------------------------------------------------------------

TIER_ARCHITECTURE_ACCESS: dict[str, set[Architecture]] = {
    "free": {Architecture.A},
    "pro":  {Architecture.A, Architecture.B},
    "team": {Architecture.A, Architecture.B, Architecture.C},
    "max":  {Architecture.A, Architecture.B, Architecture.C, Architecture.D, Architecture.E},
}


# ---------------------------------------------------------------------------
# Tier → Architecture-specific limits
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ArchitectureLimits:
    """Per-architecture limits within a pricing tier."""

    # Tool calls
    max_tool_calls_per_run: int = -1          # -1 = unlimited
    max_tool_calls_per_day: int = -1

    # Parallelism (Arch C swarm)
    max_sub_agents: int = 0
    max_parallel_agents: int = 0

    # RAG-specific (Arch B)
    max_sources_per_query: int = 0
    max_citation_hops: int = 0
    max_research_runs_per_day: int = 0

    # MCP-specific (Arch D)
    max_mcp_connections: int = 0
    max_mcp_tool_calls_per_day: int = 0

    # Long-horizon
    max_long_horizon_hours: float = 0.0
    max_long_horizon_concurrent: int = 0

    # Streaming
    streaming_enabled: bool = True

    # General
    max_runs_per_day: int = -1
    max_tokens_per_run: int = -1


# Per-tier, per-architecture limits
TIER_ARCHITECTURE_LIMITS: dict[str, dict[Architecture, ArchitectureLimits]] = {
    "free": {
        Architecture.A: ArchitectureLimits(
            max_tool_calls_per_run=50,
            max_tool_calls_per_day=500,
            max_runs_per_day=50,
            max_tokens_per_run=32_000,
            max_long_horizon_hours=0.0,
            max_long_horizon_concurrent=0,
            streaming_enabled=True,
        ),
    },
    "pro": {
        Architecture.A: ArchitectureLimits(
            max_tool_calls_per_run=200,
            max_tool_calls_per_day=5_000,
            max_runs_per_day=500,
            max_tokens_per_run=131_072,
            max_long_horizon_hours=1.0,
            max_long_horizon_concurrent=1,
            streaming_enabled=True,
        ),
        Architecture.B: ArchitectureLimits(
            max_tool_calls_per_run=100,
            max_tool_calls_per_day=2_000,
            max_sources_per_query=10,
            max_citation_hops=2,
            max_research_runs_per_day=50,
            max_runs_per_day=200,
            max_tokens_per_run=131_072,
            max_long_horizon_hours=1.0,
            max_long_horizon_concurrent=1,
            streaming_enabled=True,
        ),
    },
    "team": {
        Architecture.A: ArchitectureLimits(
            max_tool_calls_per_run=300,
            max_tool_calls_per_day=20_000,
            max_runs_per_day=1_000,
            max_tokens_per_run=262_144,
            max_long_horizon_hours=2.0,
            max_long_horizon_concurrent=3,
            streaming_enabled=True,
        ),
        Architecture.B: ArchitectureLimits(
            max_tool_calls_per_run=200,
            max_tool_calls_per_day=10_000,
            max_sources_per_query=20,
            max_citation_hops=3,
            max_research_runs_per_day=200,
            max_runs_per_day=500,
            max_tokens_per_run=262_144,
            max_long_horizon_hours=2.0,
            max_long_horizon_concurrent=2,
            streaming_enabled=True,
        ),
        Architecture.C: ArchitectureLimits(
            max_tool_calls_per_run=500,
            max_tool_calls_per_day=30_000,
            max_sub_agents=20,
            max_parallel_agents=10,
            max_runs_per_day=300,
            max_tokens_per_run=262_144,
            max_long_horizon_hours=2.0,
            max_long_horizon_concurrent=2,
            streaming_enabled=True,
        ),
    },
    "max": {
        Architecture.A: ArchitectureLimits(
            max_tool_calls_per_run=-1,
            max_tool_calls_per_day=-1,
            max_runs_per_day=-1,
            max_tokens_per_run=-1,
            max_long_horizon_hours=4.0,
            max_long_horizon_concurrent=10,
            streaming_enabled=True,
        ),
        Architecture.B: ArchitectureLimits(
            max_tool_calls_per_run=-1,
            max_tool_calls_per_day=-1,
            max_sources_per_query=-1,
            max_citation_hops=-1,
            max_research_runs_per_day=-1,
            max_runs_per_day=-1,
            max_tokens_per_run=-1,
            max_long_horizon_hours=4.0,
            max_long_horizon_concurrent=5,
            streaming_enabled=True,
        ),
        Architecture.C: ArchitectureLimits(
            max_tool_calls_per_run=-1,
            max_tool_calls_per_day=-1,
            max_sub_agents=100,
            max_parallel_agents=100,
            max_runs_per_day=-1,
            max_tokens_per_run=-1,
            max_long_horizon_hours=4.0,
            max_long_horizon_concurrent=10,
            streaming_enabled=True,
        ),
        Architecture.D: ArchitectureLimits(
            max_tool_calls_per_run=-1,
            max_tool_calls_per_day=-1,
            max_mcp_connections=-1,
            max_mcp_tool_calls_per_day=-1,
            max_runs_per_day=-1,
            max_tokens_per_run=-1,
            max_long_horizon_hours=4.0,
            max_long_horizon_concurrent=10,
            streaming_enabled=True,
        ),
        Architecture.E: ArchitectureLimits(
            max_tool_calls_per_run=-1,
            max_tool_calls_per_day=-1,
            max_sub_agents=100,
            max_parallel_agents=100,
            max_mcp_connections=-1,
            max_mcp_tool_calls_per_day=-1,
            max_sources_per_query=-1,
            max_citation_hops=-1,
            max_research_runs_per_day=-1,
            max_runs_per_day=-1,
            max_tokens_per_run=-1,
            max_long_horizon_hours=4.0,
            max_long_horizon_concurrent=10,
            streaming_enabled=True,
        ),
    },
}


# ---------------------------------------------------------------------------
# Architecture-aware usage metering
# ---------------------------------------------------------------------------

@dataclass
class ArchitectureMeter:
    """Tracks per-architecture usage within a billing period.

    Extends the flat UsageMeter with architecture-specific counters
    so that billing knows *how* resources were consumed, not just
    the totals.
    """

    user_id: str
    period_start: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )

    # Per-architecture run counts
    runs_by_arch: dict[str, int] = field(default_factory=dict)

    # Per-architecture token consumption
    tokens_by_arch: dict[str, int] = field(default_factory=dict)

    # Per-architecture tool call counts
    tool_calls_by_arch: dict[str, int] = field(default_factory=dict)

    # Architecture-specific counters
    rag_sources_fetched: int = 0
    rag_citation_hops: int = 0
    rag_research_runs: int = 0

    swarm_agents_spawned: int = 0
    swarm_peak_parallel: int = 0

    mcp_connections_opened: int = 0
    mcp_tool_calls: int = 0

    long_horizon_hours_used: float = 0.0
    long_horizon_active: int = 0

    # Cost tracking (in billing units)
    estimated_cost_units: float = 0.0

    def record_run(
        self,
        arch: str,
        tokens: int = 0,
        tool_calls: int = 0,
        cost_units: float = 0.0,
    ) -> None:
        """Record a single run on the given architecture."""
        self.runs_by_arch[arch] = self.runs_by_arch.get(arch, 0) + 1
        self.tokens_by_arch[arch] = self.tokens_by_arch.get(arch, 0) + tokens
        self.tool_calls_by_arch[arch] = (
            self.tool_calls_by_arch.get(arch, 0) + tool_calls
        )
        self.estimated_cost_units += cost_units

    def record_rag(
        self, sources: int = 0, hops: int = 0, is_research: bool = False,
    ) -> None:
        """Record RAG-specific usage (Architecture B)."""
        self.rag_sources_fetched += sources
        self.rag_citation_hops += hops
        if is_research:
            self.rag_research_runs += 1

    def record_swarm(self, agents_spawned: int = 0, peak_parallel: int = 0) -> None:
        """Record swarm-specific usage (Architecture C)."""
        self.swarm_agents_spawned += agents_spawned
        self.swarm_peak_parallel = max(self.swarm_peak_parallel, peak_parallel)

    def record_mcp(self, connections: int = 0, tool_calls: int = 0) -> None:
        """Record MCP-specific usage (Architecture D)."""
        self.mcp_connections_opened += connections
        self.mcp_tool_calls += tool_calls

    def record_long_horizon(self, hours: float = 0.0, delta_active: int = 0) -> None:
        """Record long-horizon task usage."""
        self.long_horizon_hours_used += hours
        self.long_horizon_active += delta_active

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for API responses / DynamoDB."""
        return {
            "user_id": self.user_id,
            "period_start": self.period_start.isoformat(),
            "runs_by_arch": dict(self.runs_by_arch),
            "tokens_by_arch": dict(self.tokens_by_arch),
            "tool_calls_by_arch": dict(self.tool_calls_by_arch),
            "rag": {
                "sources_fetched": self.rag_sources_fetched,
                "citation_hops": self.rag_citation_hops,
                "research_runs": self.rag_research_runs,
            },
            "swarm": {
                "agents_spawned": self.swarm_agents_spawned,
                "peak_parallel": self.swarm_peak_parallel,
            },
            "mcp": {
                "connections_opened": self.mcp_connections_opened,
                "tool_calls": self.mcp_tool_calls,
            },
            "long_horizon": {
                "hours_used": round(self.long_horizon_hours_used, 2),
                "active": self.long_horizon_active,
            },
            "estimated_cost_units": round(self.estimated_cost_units, 4),
        }


# ---------------------------------------------------------------------------
# Cost estimation
# ---------------------------------------------------------------------------

@dataclass
class CostEstimate:
    """Estimated cost for a single run on a given architecture."""

    architecture: str
    base_units: float             # raw cost units before multiplier
    multiplier: float             # architecture cost multiplier
    total_units: float            # base × multiplier
    breakdown: dict[str, float]   # component costs
    within_tier_limits: bool
    tier: str
    warnings: list[str] = field(default_factory=list)


def estimate_cost(
    architecture: str,
    tier: str = "free",
    *,
    tokens: int = 0,
    tool_calls: int = 0,
    sources: int = 0,
    sub_agents: int = 0,
    mcp_calls: int = 0,
    long_horizon_hours: float = 0.0,
) -> CostEstimate:
    """Estimate the cost of a run before executing it.

    Returns a :class:`CostEstimate` with a breakdown and tier-limit
    check.  Useful for showing users "this will cost ~X" before
    starting expensive tasks.
    """
    arch = Architecture.from_str(architecture)
    profile = ARCHITECTURE_PROFILES[arch]

    # Base cost components (in abstract "billing units")
    TOKEN_UNIT_RATE = 0.001       # per 1K tokens
    TOOL_CALL_RATE = 0.01         # per tool call
    SOURCE_RATE = 0.05            # per Sonar source fetch
    AGENT_RATE = 0.10             # per sub-agent spawned
    MCP_CALL_RATE = 0.02          # per MCP tool call
    HORIZON_RATE = 0.50           # per hour of long-horizon

    breakdown: dict[str, float] = {}
    breakdown["tokens"] = (tokens / 1_000) * TOKEN_UNIT_RATE
    breakdown["tool_calls"] = tool_calls * TOOL_CALL_RATE
    breakdown["sources"] = sources * SOURCE_RATE
    breakdown["sub_agents"] = sub_agents * AGENT_RATE
    breakdown["mcp_calls"] = mcp_calls * MCP_CALL_RATE
    breakdown["long_horizon"] = long_horizon_hours * HORIZON_RATE

    base = sum(breakdown.values())
    multiplier = profile.base_cost_multiplier
    total = base * multiplier

    # Check tier limits
    within_limits = True
    warnings: list[str] = []

    access = TIER_ARCHITECTURE_ACCESS.get(tier, set())
    if arch not in access:
        within_limits = False
        warnings.append(
            f"Architecture {arch.value} is not available on the '{tier}' tier. "
            f"Available: {sorted(a.value for a in access)}"
        )

    limits_map = TIER_ARCHITECTURE_LIMITS.get(tier, {})
    limits = limits_map.get(arch)
    if limits:
        if limits.max_tokens_per_run != -1 and tokens > limits.max_tokens_per_run:
            warnings.append(
                f"Token usage ({tokens:,}) exceeds tier limit "
                f"({limits.max_tokens_per_run:,})"
            )
            within_limits = False
        if limits.max_tool_calls_per_run != -1 and tool_calls > limits.max_tool_calls_per_run:
            warnings.append(
                f"Tool calls ({tool_calls}) exceed tier limit "
                f"({limits.max_tool_calls_per_run})"
            )
            within_limits = False
        if limits.max_sub_agents != -1 and sub_agents > limits.max_sub_agents:
            warnings.append(
                f"Sub-agents ({sub_agents}) exceed tier limit "
                f"({limits.max_sub_agents})"
            )
            within_limits = False

    return CostEstimate(
        architecture=arch.value,
        base_units=round(base, 4),
        multiplier=multiplier,
        total_units=round(total, 4),
        breakdown={k: round(v, 4) for k, v in breakdown.items()},
        within_tier_limits=within_limits,
        tier=tier,
        warnings=warnings,
    )


# ---------------------------------------------------------------------------
# Architecture billing manager
# ---------------------------------------------------------------------------

class ArchitectureBillingManager:
    """Orchestrates architecture-aware billing checks and metering.

    Sits between the API layer and the architecture backends,
    enforcing:

    1. **Feature gating** — is this architecture unlocked for the
       user's tier?
    2. **Limit checks** — is this specific run within the tier's
       per-architecture limits?
    3. **Usage metering** — record per-architecture resource
       consumption for accurate invoicing.
    4. **Cost estimation** — pre-run cost preview for expensive tasks.

    Usage::

        mgr = ArchitectureBillingManager(stripe_billing)

        # Before running
        access = await mgr.check_access(user_id, "C")
        if not access["allowed"]:
            return {"error": access["reason"]}

        estimate = mgr.estimate(user_id, "C", sub_agents=10, tool_calls=100)

        # After running
        await mgr.record(user_id, "C", tokens=50000, tool_calls=95,
                         swarm_agents=8, swarm_peak_parallel=6)
    """

    def __init__(self, billing: Any = None) -> None:
        """Initialize with an optional StripeBilling instance.

        Args:
            billing: A :class:`~orchestra.billing.StripeBilling` instance.
                     If None, all checks return "allowed" (dev mode).
        """
        self._billing = billing
        self._meters: dict[str, ArchitectureMeter] = {}
        logger.info("ArchitectureBillingManager initialised (billing=%s)",
                     "attached" if billing else "dev-mode")

    # ------------------------------------------------------------------
    # Access check
    # ------------------------------------------------------------------

    async def check_access(
        self, user_id: str, architecture: str,
    ) -> dict[str, Any]:
        """Check whether a user can use the given architecture.

        Returns:
            {
                "allowed": bool,
                "reason": str,
                "tier": str,
                "architecture": str,
                "limits": ArchitectureLimits | None,
                "upgrade_options": list[str],
            }
        """
        arch = Architecture.from_str(architecture)
        tier = await self._get_user_tier(user_id)
        access = TIER_ARCHITECTURE_ACCESS.get(tier, set())

        if arch not in access:
            # Find which tiers unlock this architecture
            upgrade_tiers = [
                t for t, archs in TIER_ARCHITECTURE_ACCESS.items()
                if arch in archs and t != tier
            ]
            return {
                "allowed": False,
                "reason": (
                    f"Architecture {arch.value} ({ARCHITECTURE_PROFILES[arch].name}) "
                    f"requires a higher tier. Your current tier: {tier}."
                ),
                "tier": tier,
                "architecture": arch.value,
                "limits": None,
                "upgrade_options": sorted(upgrade_tiers),
            }

        # Architecture is accessible — return its limits
        limits_map = TIER_ARCHITECTURE_LIMITS.get(tier, {})
        limits = limits_map.get(arch)

        # Check per-architecture daily run limits
        meter = self._get_or_create_meter(user_id)
        runs_today = meter.runs_by_arch.get(arch.value, 0)
        if limits and limits.max_runs_per_day != -1 and runs_today >= limits.max_runs_per_day:
            return {
                "allowed": False,
                "reason": (
                    f"Daily run limit for Architecture {arch.value} reached "
                    f"({runs_today}/{limits.max_runs_per_day}). "
                    f"Resets at midnight UTC."
                ),
                "tier": tier,
                "architecture": arch.value,
                "limits": limits,
                "upgrade_options": [],
            }

        # Check long-horizon concurrent limit
        if limits and limits.max_long_horizon_concurrent != -1:
            if meter.long_horizon_active >= limits.max_long_horizon_concurrent:
                return {
                    "allowed": False,
                    "reason": (
                        f"Maximum concurrent long-horizon tasks reached "
                        f"({meter.long_horizon_active}/"
                        f"{limits.max_long_horizon_concurrent})."
                    ),
                    "tier": tier,
                    "architecture": arch.value,
                    "limits": limits,
                    "upgrade_options": [],
                }

        return {
            "allowed": True,
            "reason": "Access granted",
            "tier": tier,
            "architecture": arch.value,
            "limits": limits,
            "upgrade_options": [],
        }

    # ------------------------------------------------------------------
    # Pre-run limit check
    # ------------------------------------------------------------------

    async def check_run_limits(
        self,
        user_id: str,
        architecture: str,
        *,
        tokens: int = 0,
        tool_calls: int = 0,
        sources: int = 0,
        sub_agents: int = 0,
        mcp_calls: int = 0,
        long_horizon_hours: float = 0.0,
    ) -> dict[str, Any]:
        """Validate a proposed run against the user's tier limits.

        Call this *before* executing to prevent over-limit runs.

        Returns:
            {
                "allowed": bool,
                "violations": list[str],
                "estimate": CostEstimate,
            }
        """
        arch = Architecture.from_str(architecture)
        tier = await self._get_user_tier(user_id)

        # First check access
        access = await self.check_access(user_id, architecture)
        if not access["allowed"]:
            return {
                "allowed": False,
                "violations": [access["reason"]],
                "estimate": None,
            }

        limits_map = TIER_ARCHITECTURE_LIMITS.get(tier, {})
        limits = limits_map.get(arch)
        violations: list[str] = []

        if limits:
            meter = self._get_or_create_meter(user_id)

            # Tool calls per run
            if limits.max_tool_calls_per_run != -1 and tool_calls > limits.max_tool_calls_per_run:
                violations.append(
                    f"Tool calls ({tool_calls}) exceed per-run limit "
                    f"({limits.max_tool_calls_per_run})"
                )

            # Tool calls per day (cumulative)
            day_calls = meter.tool_calls_by_arch.get(arch.value, 0) + tool_calls
            if limits.max_tool_calls_per_day != -1 and day_calls > limits.max_tool_calls_per_day:
                violations.append(
                    f"Daily tool call limit would be exceeded "
                    f"({day_calls}/{limits.max_tool_calls_per_day})"
                )

            # Tokens per run
            if limits.max_tokens_per_run != -1 and tokens > limits.max_tokens_per_run:
                violations.append(
                    f"Tokens ({tokens:,}) exceed per-run limit "
                    f"({limits.max_tokens_per_run:,})"
                )

            # Architecture-specific checks
            if arch == Architecture.B:
                if limits.max_sources_per_query != -1 and sources > limits.max_sources_per_query:
                    violations.append(
                        f"Sources ({sources}) exceed limit ({limits.max_sources_per_query})"
                    )
                if limits.max_research_runs_per_day != -1:
                    research_today = meter.rag_research_runs
                    if research_today >= limits.max_research_runs_per_day:
                        violations.append(
                            f"Daily research run limit reached "
                            f"({research_today}/{limits.max_research_runs_per_day})"
                        )

            if arch == Architecture.C:
                if limits.max_sub_agents != -1 and sub_agents > limits.max_sub_agents:
                    violations.append(
                        f"Sub-agents ({sub_agents}) exceed limit ({limits.max_sub_agents})"
                    )
                if limits.max_parallel_agents != -1 and sub_agents > limits.max_parallel_agents:
                    violations.append(
                        f"Parallel agents ({sub_agents}) exceed limit "
                        f"({limits.max_parallel_agents})"
                    )

            if arch == Architecture.D:
                if limits.max_mcp_tool_calls_per_day != -1:
                    mcp_today = meter.mcp_tool_calls + mcp_calls
                    if mcp_today > limits.max_mcp_tool_calls_per_day:
                        violations.append(
                            f"Daily MCP tool call limit would be exceeded "
                            f"({mcp_today}/{limits.max_mcp_tool_calls_per_day})"
                        )

            # Long-horizon hours
            if long_horizon_hours > 0:
                if limits.max_long_horizon_hours != -1:
                    remaining = limits.max_long_horizon_hours - meter.long_horizon_hours_used
                    if long_horizon_hours > remaining:
                        violations.append(
                            f"Long-horizon hours ({long_horizon_hours:.1f}h) exceed "
                            f"remaining allowance ({remaining:.1f}h)"
                        )

        est = estimate_cost(
            architecture, tier,
            tokens=tokens, tool_calls=tool_calls, sources=sources,
            sub_agents=sub_agents, mcp_calls=mcp_calls,
            long_horizon_hours=long_horizon_hours,
        )

        return {
            "allowed": len(violations) == 0,
            "violations": violations,
            "estimate": est,
        }

    # ------------------------------------------------------------------
    # Cost estimation (no billing object needed)
    # ------------------------------------------------------------------

    def estimate(
        self,
        user_id: str,
        architecture: str,
        **kwargs: Any,
    ) -> CostEstimate:
        """Convenience wrapper for :func:`estimate_cost`.

        Automatically injects the user's tier if billing is attached.
        """
        tier = "free"
        if self._billing:
            sub = self._billing._subscriptions.get(user_id)
            tier = sub.tier if sub else "free"
        return estimate_cost(architecture, tier, **kwargs)

    # ------------------------------------------------------------------
    # Usage recording
    # ------------------------------------------------------------------

    async def record(
        self,
        user_id: str,
        architecture: str,
        *,
        tokens: int = 0,
        tool_calls: int = 0,
        # RAG-specific
        sources: int = 0,
        citation_hops: int = 0,
        is_research: bool = False,
        # Swarm-specific
        swarm_agents: int = 0,
        swarm_peak_parallel: int = 0,
        # MCP-specific
        mcp_connections: int = 0,
        mcp_tool_calls: int = 0,
        # Long-horizon
        long_horizon_hours: float = 0.0,
        long_horizon_delta: int = 0,
    ) -> ArchitectureMeter:
        """Record usage after a run completes.

        Updates both the architecture-specific meter and the base
        StripeBilling usage meter (for aggregated limit checks).
        """
        arch = Architecture.from_str(architecture)
        profile = ARCHITECTURE_PROFILES[arch]
        meter = self._get_or_create_meter(user_id)

        # Calculate cost units
        cost = estimate_cost(
            architecture, await self._get_user_tier(user_id),
            tokens=tokens, tool_calls=tool_calls, sources=sources,
            sub_agents=swarm_agents, mcp_calls=mcp_tool_calls,
            long_horizon_hours=long_horizon_hours,
        )

        # Record to architecture meter
        meter.record_run(
            arch.value,
            tokens=tokens,
            tool_calls=tool_calls,
            cost_units=cost.total_units,
        )

        if arch == Architecture.B:
            meter.record_rag(sources, citation_hops, is_research)

        if arch == Architecture.C:
            meter.record_swarm(swarm_agents, swarm_peak_parallel)

        if arch == Architecture.D:
            meter.record_mcp(mcp_connections, mcp_tool_calls)

        if long_horizon_hours > 0 or long_horizon_delta != 0:
            meter.record_long_horizon(long_horizon_hours, long_horizon_delta)

        # Forward aggregate totals to StripeBilling for global limit checks
        if self._billing:
            await self._billing.record_usage(
                user_id,
                requests=1,
                tokens=tokens,
                agents=swarm_agents,
            )

        logger.info(
            "Recorded arch=%s user=%s tokens=%d tool_calls=%d cost=%.4f",
            arch.value, user_id, tokens, tool_calls, cost.total_units,
        )
        return meter

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_usage_report(self, user_id: str) -> dict[str, Any]:
        """Return the full architecture-aware usage report for a user."""
        meter = self._meters.get(user_id)
        if meter is None:
            return {"user_id": user_id, "usage": None}
        return {"user_id": user_id, "usage": meter.to_dict()}

    def get_architecture_summary(self) -> dict[str, Any]:
        """Return a summary of all architecture profiles and tier access."""
        summary: dict[str, Any] = {}
        for arch, profile in ARCHITECTURE_PROFILES.items():
            available_on = [
                tier for tier, archs in TIER_ARCHITECTURE_ACCESS.items()
                if arch in archs
            ]
            summary[arch.value] = {
                "name": profile.name,
                "description": profile.description,
                "cost_multiplier": profile.base_cost_multiplier,
                "available_on_tiers": sorted(available_on),
                "supports": {
                    "multi_hop": profile.supports_multi_hop,
                    "swarm": profile.supports_swarm,
                    "mcp": profile.supports_mcp,
                    "long_horizon": profile.supports_long_horizon,
                    "streaming": profile.supports_streaming,
                    "adaptive_context": profile.supports_adaptive_context,
                },
            }
        return summary

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_user_tier(self, user_id: str) -> str:
        """Resolve the user's current tier from StripeBilling."""
        if self._billing is None:
            return "max"  # dev mode: everything unlocked
        sub = await self._billing.get_subscription(user_id)
        return sub.tier if sub else "free"

    def _get_or_create_meter(self, user_id: str) -> ArchitectureMeter:
        """Get or create the architecture-aware meter for a user."""
        meter = self._meters.get(user_id)
        if meter is None:
            meter = ArchitectureMeter(user_id=user_id)
            self._meters[user_id] = meter
        return meter


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def check_architecture_access(tier: str, architecture: str) -> dict[str, Any]:
    """Synchronous check: is this architecture available on this tier?

    Useful for fast gating without async or a billing instance.
    """
    arch = Architecture.from_str(architecture)
    access = TIER_ARCHITECTURE_ACCESS.get(tier, set())

    if arch not in access:
        upgrade_tiers = [
            t for t, archs in TIER_ARCHITECTURE_ACCESS.items()
            if arch in archs
        ]
        return {
            "allowed": False,
            "reason": (
                f"Architecture {arch.value} requires: "
                f"{', '.join(sorted(upgrade_tiers))}"
            ),
            "upgrade_options": sorted(upgrade_tiers),
        }
    return {"allowed": True, "reason": "Access granted", "upgrade_options": []}
