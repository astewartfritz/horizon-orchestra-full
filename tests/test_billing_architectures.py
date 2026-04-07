"""Tests for architecture-aware billing system.

Run with: pytest tests/test_billing_architectures.py -v
"""
from __future__ import annotations

import asyncio
import pytest

def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ===================================================================
# Architecture enum
# ===================================================================

class TestArchitectureEnum:

    def test_all_values(self):
        from orchestra.billing import Architecture
        assert set(a.value for a in Architecture) == {"A", "B", "C", "D", "E"}

    def test_from_str(self):
        from orchestra.billing import Architecture
        assert Architecture.from_str("A") == Architecture.A
        assert Architecture.from_str("b") == Architecture.B
        assert Architecture.from_str("ARCH_C") == Architecture.C
        assert Architecture.from_str("d") == Architecture.D

    def test_from_str_invalid(self):
        from orchestra.billing import Architecture
        with pytest.raises(ValueError, match="Unknown architecture"):
            Architecture.from_str("X")


# ===================================================================
# Architecture profiles
# ===================================================================

class TestArchitectureProfiles:

    def test_all_architectures_have_profiles(self):
        from orchestra.billing import Architecture, ARCHITECTURE_PROFILES
        for arch in Architecture:
            assert arch in ARCHITECTURE_PROFILES

    def test_cost_multipliers_ordered(self):
        from orchestra.billing import Architecture, ARCHITECTURE_PROFILES
        # A should be cheapest, C most expensive (among individual archs)
        assert ARCHITECTURE_PROFILES[Architecture.A].base_cost_multiplier == 1.0
        assert ARCHITECTURE_PROFILES[Architecture.C].base_cost_multiplier > ARCHITECTURE_PROFILES[Architecture.A].base_cost_multiplier

    def test_swarm_profile(self):
        from orchestra.billing import Architecture, ARCHITECTURE_PROFILES
        c = ARCHITECTURE_PROFILES[Architecture.C]
        assert c.supports_swarm is True
        assert c.max_parallel_agents == 100

    def test_rag_profile(self):
        from orchestra.billing import Architecture, ARCHITECTURE_PROFILES
        b = ARCHITECTURE_PROFILES[Architecture.B]
        assert b.supports_multi_hop is True

    def test_mcp_profile(self):
        from orchestra.billing import Architecture, ARCHITECTURE_PROFILES
        d = ARCHITECTURE_PROFILES[Architecture.D]
        assert d.supports_mcp is True


# ===================================================================
# Tier access mapping
# ===================================================================

class TestTierAccess:

    def test_free_only_arch_a(self):
        from orchestra.billing import TIER_ARCHITECTURE_ACCESS, Architecture
        assert TIER_ARCHITECTURE_ACCESS["free"] == {Architecture.A}

    def test_pro_a_and_b(self):
        from orchestra.billing import TIER_ARCHITECTURE_ACCESS, Architecture
        assert TIER_ARCHITECTURE_ACCESS["pro"] == {Architecture.A, Architecture.B}

    def test_team_a_b_c(self):
        from orchestra.billing import TIER_ARCHITECTURE_ACCESS, Architecture
        assert TIER_ARCHITECTURE_ACCESS["team"] == {Architecture.A, Architecture.B, Architecture.C}

    def test_max_all(self):
        from orchestra.billing import TIER_ARCHITECTURE_ACCESS, Architecture
        assert TIER_ARCHITECTURE_ACCESS["max"] == set(Architecture)

    def test_sync_check_denied(self):
        from orchestra.billing import check_architecture_access
        result = check_architecture_access("free", "C")
        assert result["allowed"] is False
        assert "max" in result["upgrade_options"] or "team" in result["upgrade_options"]

    def test_sync_check_allowed(self):
        from orchestra.billing import check_architecture_access
        result = check_architecture_access("max", "D")
        assert result["allowed"] is True


# ===================================================================
# Per-tier architecture limits
# ===================================================================

class TestTierLimits:

    def test_free_arch_a_limits(self):
        from orchestra.billing import TIER_ARCHITECTURE_LIMITS, Architecture
        limits = TIER_ARCHITECTURE_LIMITS["free"][Architecture.A]
        assert limits.max_tool_calls_per_run == 50
        assert limits.max_runs_per_day == 50
        assert limits.max_long_horizon_hours == 0.0

    def test_pro_arch_b_limits(self):
        from orchestra.billing import TIER_ARCHITECTURE_LIMITS, Architecture
        limits = TIER_ARCHITECTURE_LIMITS["pro"][Architecture.B]
        assert limits.max_sources_per_query == 10
        assert limits.max_citation_hops == 2
        assert limits.max_research_runs_per_day == 50

    def test_team_arch_c_limits(self):
        from orchestra.billing import TIER_ARCHITECTURE_LIMITS, Architecture
        limits = TIER_ARCHITECTURE_LIMITS["team"][Architecture.C]
        assert limits.max_sub_agents == 20
        assert limits.max_parallel_agents == 10

    def test_max_unlimited(self):
        from orchestra.billing import TIER_ARCHITECTURE_LIMITS, Architecture
        limits = TIER_ARCHITECTURE_LIMITS["max"][Architecture.A]
        assert limits.max_tool_calls_per_run == -1
        assert limits.max_runs_per_day == -1

    def test_max_arch_d_limits(self):
        from orchestra.billing import TIER_ARCHITECTURE_LIMITS, Architecture
        limits = TIER_ARCHITECTURE_LIMITS["max"][Architecture.D]
        assert limits.max_mcp_connections == -1
        assert limits.max_mcp_tool_calls_per_day == -1


# ===================================================================
# Cost estimation
# ===================================================================

class TestCostEstimation:

    def test_basic_estimate(self):
        from orchestra.billing import estimate_cost
        est = estimate_cost("A", "free", tokens=8000, tool_calls=15)
        assert est.architecture == "A"
        assert est.multiplier == 1.0
        assert est.total_units > 0
        assert est.within_tier_limits is True

    def test_arch_c_more_expensive(self):
        from orchestra.billing import estimate_cost
        est_a = estimate_cost("A", "max", tokens=8000, tool_calls=15)
        est_c = estimate_cost("C", "max", tokens=8000, tool_calls=15)
        # Same inputs, but C has a higher multiplier
        assert est_c.total_units > est_a.total_units

    def test_out_of_tier_warning(self):
        from orchestra.billing import estimate_cost
        est = estimate_cost("D", "pro")
        assert est.within_tier_limits is False
        assert len(est.warnings) > 0
        assert "not available" in est.warnings[0]

    def test_breakdown_components(self):
        from orchestra.billing import estimate_cost
        est = estimate_cost("B", "pro", tokens=20000, sources=10, tool_calls=5)
        assert "tokens" in est.breakdown
        assert "sources" in est.breakdown
        assert "tool_calls" in est.breakdown
        assert est.breakdown["sources"] > 0

    def test_long_horizon_cost(self):
        from orchestra.billing import estimate_cost
        est = estimate_cost("A", "max", long_horizon_hours=2.0)
        assert est.breakdown["long_horizon"] > 0


# ===================================================================
# Architecture meter
# ===================================================================

class TestArchitectureMeter:

    def test_record_run(self):
        from orchestra.billing import ArchitectureMeter
        meter = ArchitectureMeter(user_id="test")
        meter.record_run("A", tokens=5000, tool_calls=10, cost_units=0.5)
        assert meter.runs_by_arch["A"] == 1
        assert meter.tokens_by_arch["A"] == 5000
        assert meter.tool_calls_by_arch["A"] == 10
        assert meter.estimated_cost_units == 0.5

    def test_record_rag(self):
        from orchestra.billing import ArchitectureMeter
        meter = ArchitectureMeter(user_id="test")
        meter.record_rag(sources=5, hops=2, is_research=True)
        assert meter.rag_sources_fetched == 5
        assert meter.rag_citation_hops == 2
        assert meter.rag_research_runs == 1

    def test_record_swarm(self):
        from orchestra.billing import ArchitectureMeter
        meter = ArchitectureMeter(user_id="test")
        meter.record_swarm(agents_spawned=8, peak_parallel=6)
        assert meter.swarm_agents_spawned == 8
        assert meter.swarm_peak_parallel == 6

    def test_record_mcp(self):
        from orchestra.billing import ArchitectureMeter
        meter = ArchitectureMeter(user_id="test")
        meter.record_mcp(connections=3, tool_calls=45)
        assert meter.mcp_connections_opened == 3
        assert meter.mcp_tool_calls == 45

    def test_to_dict(self):
        from orchestra.billing import ArchitectureMeter
        meter = ArchitectureMeter(user_id="test")
        meter.record_run("B", tokens=10000, tool_calls=5)
        meter.record_rag(sources=3, hops=1)
        d = meter.to_dict()
        assert d["user_id"] == "test"
        assert "runs_by_arch" in d
        assert "rag" in d
        assert d["rag"]["sources_fetched"] == 3


# ===================================================================
# ArchitectureBillingManager
# ===================================================================

class TestBillingManager:

    def test_dev_mode_allows_everything(self):
        from orchestra.billing import ArchitectureBillingManager
        mgr = ArchitectureBillingManager(billing=None)
        result = _run(mgr.check_access("user1", "D"))
        assert result["allowed"] is True
        assert result["tier"] == "max"

    def test_estimate_dev_mode(self):
        from orchestra.billing import ArchitectureBillingManager
        mgr = ArchitectureBillingManager(billing=None)
        est = mgr.estimate("user1", "C", tokens=50000, sub_agents=10)
        assert est.total_units > 0
        # In dev mode (no billing), estimate uses 'free' since no subscription exists
        # but check_access returns 'max' — the estimate is still valid
        assert est.architecture == "C"

    def test_usage_report_empty(self):
        from orchestra.billing import ArchitectureBillingManager
        mgr = ArchitectureBillingManager(billing=None)
        report = mgr.get_usage_report("nobody")
        assert report["usage"] is None

    def test_architecture_summary(self):
        from orchestra.billing import ArchitectureBillingManager
        mgr = ArchitectureBillingManager(billing=None)
        summary = mgr.get_architecture_summary()
        assert "A" in summary
        assert "B" in summary
        assert "C" in summary
        assert "D" in summary
        assert "E" in summary
        assert summary["C"]["supports"]["swarm"] is True
        assert summary["B"]["supports"]["multi_hop"] is True

    def test_record_and_report(self):
        from orchestra.billing import ArchitectureBillingManager
        mgr = ArchitectureBillingManager(billing=None)
        _run(mgr.record("user1", "A", tokens=5000, tool_calls=10))
        _run(mgr.record("user1", "B", tokens=20000, sources=8, citation_hops=2))
        report = mgr.get_usage_report("user1")
        usage = report["usage"]
        assert usage["runs_by_arch"]["A"] == 1
        assert usage["runs_by_arch"]["B"] == 1
        assert usage["rag"]["sources_fetched"] == 8


# ===================================================================
# Billing middleware
# ===================================================================

class TestBillingMiddleware:

    def test_middleware_creation(self):
        from orchestra.billing import BillingMiddleware, ArchitectureBillingManager
        mgr = ArchitectureBillingManager(billing=None)
        mw = BillingMiddleware(mgr)
        assert mw is not None

    def test_wrap_agent(self):
        from orchestra.billing import BillingMiddleware, ArchitectureBillingManager, BillingWrappedAgent

        class FakeAgent:
            async def run(self, task, **kw):
                return "done"

        mgr = ArchitectureBillingManager(billing=None)
        mw = BillingMiddleware(mgr)
        wrapped = mw.wrap(FakeAgent(), architecture="A", user_id="user1")
        assert isinstance(wrapped, BillingWrappedAgent)

    def test_wrapped_run(self):
        from orchestra.billing import BillingMiddleware, ArchitectureBillingManager

        class FakeAgent:
            last_tool_call_count = 5
            async def run(self, task, **kw):
                return "result from agent"

        mgr = ArchitectureBillingManager(billing=None)
        mw = BillingMiddleware(mgr)
        wrapped = mw.wrap(FakeAgent(), architecture="A", user_id="user1")
        result = _run(wrapped.run("test task"))
        assert result == "result from agent"

    def test_billing_event_dataclass(self):
        from orchestra.billing import BillingEvent
        event = BillingEvent(
            type="billing_check",
            architecture="C",
            user_id="user1",
            data={"estimate": 5.0},
        )
        d = event.to_dict()
        assert d["type"] == "billing_check"
        assert d["architecture"] == "C"
        assert d["data"]["estimate"] == 5.0


# ===================================================================
# Pricing tiers reflect architectures
# ===================================================================

class TestPricingTiersArchitectures:

    def test_free_tier_features_mention_arch_a(self):
        from orchestra.billing import PRICING_TIERS
        features = PRICING_TIERS["free"].features
        assert any("Architecture A" in f for f in features)

    def test_pro_tier_features_mention_rag(self):
        from orchestra.billing import PRICING_TIERS
        features = PRICING_TIERS["pro"].features
        assert any("RAG" in f for f in features)
        assert any("research" in f.lower() for f in features)

    def test_team_tier_features_mention_swarm(self):
        from orchestra.billing import PRICING_TIERS
        features = PRICING_TIERS["team"].features
        assert any("Swarm" in f for f in features)

    def test_max_tier_features_mention_all(self):
        from orchestra.billing import PRICING_TIERS
        features = PRICING_TIERS["max"].features
        assert any("All Architectures" in f for f in features)
        assert any("MCP" in f for f in features)

    def test_all_tiers_have_architectures_in_limits(self):
        from orchestra.billing import PRICING_TIERS
        for name, tier in PRICING_TIERS.items():
            assert "architectures" in tier.limits, f"Tier '{name}' missing architectures in limits"


# ===================================================================
# Full import smoke
# ===================================================================

class TestBillingImportSmoke:

    def test_all_billing_modules(self):
        import importlib
        mods = [
            "orchestra.billing",
            "orchestra.billing.stripe_billing",
            "orchestra.billing.architecture_billing",
            "orchestra.billing.middleware",
        ]
        for m in mods:
            importlib.import_module(m)
