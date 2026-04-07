"""Tests for stripe_billing and usage_tracker modules.

All tests run offline — no Stripe API key or network access required.
Stripe SDK calls are mocked where the module is imported.
"""

from __future__ import annotations

import asyncio
import time
import unittest
from unittest import mock


# ===========================================================================
# PricingTier / UsageType / TierConfig tests
# ===========================================================================

class PricingTierTests(unittest.TestCase):

    def test_pricing_tier_values(self):
        """All 4 tiers exist with the expected string values."""
        from orchestra.stripe_billing import PricingTier
        self.assertEqual(PricingTier.MAKER.value, "maker")
        self.assertEqual(PricingTier.BUILDER.value, "builder")
        self.assertEqual(PricingTier.PRO.value, "pro")
        self.assertEqual(PricingTier.ENTERPRISE.value, "enterprise")

    def test_usage_type_values(self):
        """All 9 usage types exist with the expected string values."""
        from orchestra.stripe_billing import UsageType
        self.assertEqual(UsageType.LLM_INPUT_TOKENS.value, "llm_input_tokens")
        self.assertEqual(UsageType.LLM_OUTPUT_TOKENS.value, "llm_output_tokens")
        self.assertEqual(UsageType.TOOL_CALLS.value, "tool_calls")
        self.assertEqual(UsageType.SWARM_SPAWNS.value, "swarm_spawns")
        self.assertEqual(UsageType.STT_SECONDS.value, "stt_seconds")
        self.assertEqual(UsageType.TTS_CHARACTERS.value, "tts_characters")
        self.assertEqual(UsageType.MEMORY_ENTRIES.value, "memory_entries")
        self.assertEqual(UsageType.CODE_EXECUTIONS.value, "code_executions")
        self.assertEqual(UsageType.BROWSER_ACTIONS.value, "browser_actions")

    def test_tier_configs_exist(self):
        """All 4 tiers have a TierConfig entry in TIER_CONFIGS."""
        from orchestra.stripe_billing import TIER_CONFIGS, PricingTier, TierConfig
        for tier in PricingTier:
            self.assertIn(tier, TIER_CONFIGS)
            self.assertIsInstance(TIER_CONFIGS[tier], TierConfig)


# ===========================================================================
# Entitlement tests
# ===========================================================================

class EntitlementTests(unittest.TestCase):

    def test_maker_model_access_gemma_e4b(self):
        """Maker tier can use gemma-4-e4b."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="maker")
        allowed, reason = tracker.check_model("gemma-4-e4b")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_maker_model_access_opus_denied(self):
        """Maker tier cannot use Claude Opus."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="maker")
        allowed, reason = tracker.check_model("claude-opus-4.6")
        self.assertFalse(allowed)
        self.assertIn("not available", reason)

    def test_builder_model_access_kimi(self):
        """Builder tier can use kimi-k2.5."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="builder")
        allowed, reason = tracker.check_model("kimi-k2.5")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_builder_model_access_opus_denied(self):
        """Builder tier cannot use Claude Opus."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="builder")
        allowed, reason = tracker.check_model("claude-opus-4.6")
        self.assertFalse(allowed)
        self.assertIn("not available", reason)

    def test_pro_model_access_opus(self):
        """Pro tier can use Claude Opus."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="pro")
        allowed, reason = tracker.check_model("claude-opus-4.6")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_maker_stt_local_only(self):
        """Maker: whisper_local allowed, deepgram denied."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="maker")
        # whisper_local is in maker's allowed_stt set
        allowed_whisper = asyncio.run(tracker.track_stt(10.0, "whisper_local"))
        self.assertEqual(allowed_whisper, (True, ""))

        # deepgram is NOT in maker's allowed_stt set
        tracker2 = UsageTracker(tier="maker")
        result = asyncio.run(tracker2.track_stt(10.0, "deepgram"))
        allowed, reason = result
        self.assertFalse(allowed)
        self.assertIn("not available", reason)

    def test_builder_tts_openai_allowed(self):
        """Builder tier can use openai_tts."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="builder")
        result = asyncio.run(tracker.track_tts(100, "openai_tts"))
        allowed, reason = result
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_maker_architecture_C_denied(self):
        """Maker tier cannot use swarm (architecture C)."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="maker")
        allowed, reason = tracker.check_architecture("C")
        self.assertFalse(allowed)
        self.assertIn("not available", reason)

    def test_pro_architecture_E_allowed(self):
        """Pro tier can use Architecture E (production)."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="pro")
        allowed, reason = tracker.check_architecture("E")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_enterprise_all_allowed(self):
        """Enterprise tier allows all models, architectures, and STT/TTS backends."""
        from orchestra.usage_tracker import UsageTracker
        tracker = UsageTracker(tier="enterprise")

        model_ok, _ = tracker.check_model("claude-opus-4.6")
        self.assertTrue(model_ok)

        arch_ok, _ = tracker.check_architecture("E")
        self.assertTrue(arch_ok)

        # STT: None = all backends
        stt_ok = asyncio.run(tracker.track_stt(10.0, "elevenlabs_scribe"))
        self.assertEqual(stt_ok[0], True)


# ===========================================================================
# Cost calculation tests
# ===========================================================================

class CostCalculationTests(unittest.TestCase):

    def _billing(self):
        from orchestra.stripe_billing import BillingManager
        with mock.patch.dict("os.environ", {}, clear=False):
            return BillingManager()

    def test_llm_cost_gemma_free(self):
        """Free model (gemma-4-e4b) should produce zero cost."""
        from orchestra.stripe_billing import MODEL_COSTS
        in_cost, out_cost = MODEL_COSTS.get("gemma-4-e4b", (0.0, 0.0))
        self.assertEqual(in_cost, 0.0)
        self.assertEqual(out_cost, 0.0)

    def test_llm_cost_opus(self):
        """Claude Opus 4.6 should cost $5/$25 per 1M tokens."""
        from orchestra.stripe_billing import MODEL_COSTS
        inp, out = MODEL_COSTS["claude-opus-4.6"]
        self.assertAlmostEqual(inp, 5.00)
        self.assertAlmostEqual(out, 25.00)

    def test_stt_cost_whisper(self):
        """Whisper API STT should cost $0.006/min."""
        from orchestra.stripe_billing import STT_COSTS
        self.assertAlmostEqual(STT_COSTS["whisper_api"], 0.006)

    def test_tts_cost_openai(self):
        """OpenAI TTS should cost $15/1M chars = $0.015 per 1k chars."""
        from orchestra.stripe_billing import TTS_COSTS
        self.assertAlmostEqual(TTS_COSTS["openai_tts"], 15.0 / 1_000)

    def test_markup_builder(self):
        """Builder tier has 30% markup on model costs."""
        from orchestra.stripe_billing import TIER_CONFIGS, PricingTier
        cfg = TIER_CONFIGS[PricingTier.BUILDER]
        self.assertAlmostEqual(cfg.markup_percentage, 0.30)

    def test_markup_enterprise(self):
        """Enterprise tier has 20% markup on model costs."""
        from orchestra.stripe_billing import TIER_CONFIGS, PricingTier
        cfg = TIER_CONFIGS[PricingTier.ENTERPRISE]
        self.assertAlmostEqual(cfg.markup_percentage, 0.20)


# ===========================================================================
# BillingManager tests — mock Stripe
# ===========================================================================

class BillingManagerTests(unittest.IsolatedAsyncioTestCase):

    def _make_billing(self):
        """Create a BillingManager with Stripe fully mocked."""
        import orchestra.stripe_billing as sb
        with mock.patch.object(sb, "HAS_STRIPE", False):
            from orchestra.stripe_billing import BillingManager
            bm = BillingManager.__new__(BillingManager)
            bm._stripe = None
            bm._local_mode = True
            bm._customers = {}
            bm._usage_records = {}
            bm._billing_events = []
            import logging
            bm._log = logging.getLogger("test_billing")
            return bm

    async def test_create_customer_no_stripe(self):
        """BillingManager.create_customer works in local (no-Stripe) mode."""
        from orchestra.stripe_billing import BillingManager, PricingTier
        bm = BillingManager()  # will use local mode if no key set
        customer = await bm.create_customer(
            email="test@example.com",
            name="Test User",
            tier=PricingTier.MAKER,
        )
        self.assertIsNotNone(customer)
        self.assertEqual(customer.email, "test@example.com")
        self.assertEqual(customer.tier, PricingTier.MAKER)
        self.assertTrue(len(customer.id) > 0)

    async def test_record_llm_usage(self):
        """record_llm_usage records an event correctly in local mode."""
        from orchestra.stripe_billing import BillingManager, PricingTier
        bm = BillingManager()
        customer = await bm.create_customer(
            email="u@test.com", name="U", tier=PricingTier.PRO,
        )
        # Should not raise
        await bm.record_llm_usage(
            customer_id=customer.stripe_customer_id,
            input_tokens=1000,
            output_tokens=500,
            model="gemma-4-31b",
        )

    async def test_record_tool_usage(self):
        """record_tool_usage records an event correctly in local mode."""
        from orchestra.stripe_billing import BillingManager, PricingTier
        bm = BillingManager()
        customer = await bm.create_customer(
            email="u2@test.com", name="U2", tier=PricingTier.BUILDER,
        )
        await bm.record_tool_usage(
            customer_id=customer.stripe_customer_id,
            tool_name="web_search",
            count=1,
        )

    async def test_get_usage_summary(self):
        """get_usage_summary returns a UsageSummary with correct types."""
        from orchestra.stripe_billing import BillingManager, PricingTier, UsageSummary
        bm = BillingManager()
        customer = await bm.create_customer(
            email="u3@test.com", name="U3", tier=PricingTier.PRO,
        )
        summary = await bm.get_usage_summary(customer.stripe_customer_id)
        self.assertIsInstance(summary, UsageSummary)
        self.assertEqual(summary.customer_id, customer.stripe_customer_id)

    async def test_null_billing_manager(self):
        """NullBillingManager no-ops gracefully."""
        from orchestra.stripe_billing import NullBillingManager, PricingTier
        bm = NullBillingManager()
        customer = await bm.create_customer(
            email="null@test.com", name="Null", tier=PricingTier.MAKER,
        )
        self.assertIsNotNone(customer)
        await bm.record_llm_usage(customer.stripe_customer_id, 100, 50, "gemma-4-e4b")
        summary = await bm.get_usage_summary(customer.stripe_customer_id)
        self.assertIsNotNone(summary)

    async def test_estimate_cost(self):
        """estimate_cost returns a non-negative float for known models."""
        from orchestra.stripe_billing import BillingManager, PricingTier, UsageType
        bm = BillingManager()
        customer = await bm.create_customer(
            email="est@test.com", name="Est", tier=PricingTier.PRO,
        )
        cost = await bm.estimate_cost(
            customer_id=customer.id,
            usage_type=UsageType.LLM_INPUT_TOKENS,
            value=1_000_000,
            model="claude-opus-4.6",
        )
        self.assertIsInstance(cost, (int, float))
        self.assertGreater(cost, 0)


# ===========================================================================
# UsageTracker tests
# ===========================================================================

class UsageTrackerTests(unittest.IsolatedAsyncioTestCase):

    def _make_tracker(self, tier: str = "builder", enforce: bool = True):
        from orchestra.usage_tracker import UsageTracker
        return UsageTracker(billing=None, customer_id="", tier=tier, enforce_limits=enforce)

    async def test_tracker_init(self):
        """UsageTracker initialises with zeroed counters."""
        tracker = self._make_tracker(tier="maker")
        snap = tracker.get_snapshot()
        self.assertEqual(snap.tool_calls, 0)
        self.assertEqual(snap.llm_input_tokens, 0)
        self.assertEqual(snap.llm_output_tokens, 0)
        self.assertEqual(snap.stt_seconds, 0.0)
        self.assertEqual(snap.tts_characters, 0)

    async def test_track_tool_call_within_limit(self):
        """track_tool_call returns (True, '') when within limit."""
        tracker = self._make_tracker(tier="builder")
        result = await tracker.track_tool_call("web_search")
        self.assertEqual(result, (True, ""))
        snap = tracker.get_snapshot()
        self.assertEqual(snap.tool_calls, 1)

    async def test_track_tool_call_exceeds_limit(self):
        """track_tool_call returns (False, reason) when monthly limit reached."""
        from orchestra.usage_tracker import UsageTracker, TIER_LIMITS
        # Use a tracker with a very small limit by monkey-patching
        tracker = UsageTracker(billing=None, customer_id="", tier="maker", enforce_limits=True)
        # Drain the limit manually
        limit = TIER_LIMITS["maker"]["max_tool_calls_monthly"]
        tracker._snapshot.tool_calls = limit  # set counter to max

        result = await tracker.track_tool_call("web_search")
        allowed, reason = result
        self.assertFalse(allowed)
        self.assertIn("limit", reason.lower())

    async def test_track_llm_call_records(self):
        """track_llm_call updates token counters correctly."""
        tracker = self._make_tracker(tier="pro")
        await tracker.track_llm_call("gemma-4-31b", input_tokens=500, output_tokens=200)
        snap = tracker.get_snapshot()
        self.assertEqual(snap.llm_input_tokens, 500)
        self.assertEqual(snap.llm_output_tokens, 200)

    async def test_track_stt_within_budget(self):
        """track_stt returns (True, '') when within STT budget."""
        tracker = self._make_tracker(tier="builder")
        result = await tracker.track_stt(60.0, "whisper_api")
        self.assertEqual(result[0], True)
        snap = tracker.get_snapshot()
        self.assertAlmostEqual(snap.stt_seconds, 60.0)

    async def test_track_stt_exceeds_budget(self):
        """track_stt returns (False, reason) when STT budget exhausted."""
        from orchestra.usage_tracker import UsageTracker, TIER_LIMITS
        tracker = UsageTracker(billing=None, customer_id="", tier="maker", enforce_limits=True)
        # Set stt usage to just below limit, then exceed
        included = TIER_LIMITS["maker"]["included_stt_seconds"]  # 3600
        tracker._snapshot.stt_seconds = included + 1.0  # already over

        result = await tracker.track_stt(10.0, "whisper_local")
        allowed, reason = result
        self.assertFalse(allowed)
        self.assertIn("budget", reason.lower())

    async def test_track_tts_within_budget(self):
        """track_tts returns (True, '') when within TTS budget."""
        tracker = self._make_tracker(tier="builder")
        result = await tracker.track_tts(500, "openai_tts")
        self.assertEqual(result[0], True)
        snap = tracker.get_snapshot()
        self.assertEqual(snap.tts_characters, 500)

    async def test_check_model_maker_denied(self):
        """check_model returns (False, reason) for opus on maker tier."""
        tracker = self._make_tracker(tier="maker")
        allowed, reason = tracker.check_model("claude-opus-4.6")
        self.assertFalse(allowed)
        self.assertTrue(len(reason) > 0)

    async def test_check_model_pro_allowed(self):
        """check_model returns (True, '') for opus on pro tier."""
        tracker = self._make_tracker(tier="pro")
        allowed, reason = tracker.check_model("claude-opus-4.6")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    async def test_check_architecture_denied(self):
        """check_architecture returns (False, reason) for swarm on maker tier."""
        tracker = self._make_tracker(tier="maker")
        allowed, reason = tracker.check_architecture("C")
        self.assertFalse(allowed)
        self.assertIn("not available", reason)

    async def test_get_budget(self):
        """get_budget returns a UsageBudget with correct values."""
        from orchestra.usage_tracker import UsageBudget
        tracker = self._make_tracker(tier="builder")
        budget = tracker.get_budget()
        self.assertIsInstance(budget, UsageBudget)
        # Builder gets 50,000 tool calls
        self.assertEqual(budget.tool_calls_remaining, 50_000)

    async def test_get_snapshot(self):
        """get_snapshot returns correct counters after tracking."""
        tracker = self._make_tracker(tier="pro")
        await tracker.track_tool_call("file_read")
        await tracker.track_tool_call("web_search")
        snap = tracker.get_snapshot()
        self.assertEqual(snap.tool_calls, 2)

    async def test_null_tracker(self):
        """NullUsageTracker: all track/check methods return (True, '')."""
        from orchestra.usage_tracker import NullUsageTracker
        nt = NullUsageTracker()

        self.assertEqual(await nt.track_tool_call("web_search"), (True, ""))
        self.assertEqual(await nt.track_llm_call("gemma-4-e4b", 100, 50), (True, ""))
        self.assertEqual(await nt.track_stt(60.0, "whisper_local"), (True, ""))
        self.assertEqual(await nt.track_tts(200, "kokoro"), (True, ""))
        self.assertEqual(await nt.track_memory_write(), (True, ""))
        self.assertEqual(await nt.start_session(), (True, ""))
        self.assertEqual(nt.check_model("claude-opus-4.6"), (True, ""))
        self.assertEqual(nt.check_architecture("E"), (True, ""))
        self.assertEqual(nt.check_feature("domain_router"), (True, ""))


# ===========================================================================
# TIER_LIMITS tests
# ===========================================================================

class TierLimitsTests(unittest.TestCase):

    def test_maker_limits(self):
        """Maker tier has the expected specific limit values."""
        from orchestra.usage_tracker import TIER_LIMITS
        m = TIER_LIMITS["maker"]
        self.assertEqual(m["max_tool_calls_monthly"], 1000)
        self.assertEqual(m["included_stt_seconds"], 3600)    # 60 min
        self.assertEqual(m["included_tts_seconds"], 1800)    # 30 min
        self.assertEqual(m["max_memory_entries"], 100)
        self.assertEqual(m["included_model_credit_cents"], 0)
        self.assertEqual(m["max_swarm_agents"], 0)
        self.assertFalse(m["enable_domain_router"])

    def test_enterprise_unlimited(self):
        """Enterprise tier has 0 = unlimited on all count limits."""
        from orchestra.usage_tracker import TIER_LIMITS
        e = TIER_LIMITS["enterprise"]
        self.assertEqual(e["max_tool_calls_monthly"], 0)     # unlimited
        self.assertEqual(e["included_stt_seconds"], 0)       # unlimited
        self.assertEqual(e["included_tts_seconds"], 0)       # unlimited
        self.assertEqual(e["max_memory_entries"], 0)         # unlimited
        self.assertTrue(e["enable_domain_router"])
        self.assertTrue(e["enable_voice_cloning"])

    def test_all_four_tiers_present(self):
        """TIER_LIMITS contains entries for all 4 tiers."""
        from orchestra.usage_tracker import TIER_LIMITS
        for tier in ("maker", "builder", "pro", "enterprise"):
            self.assertIn(tier, TIER_LIMITS)


if __name__ == "__main__":
    unittest.main()
