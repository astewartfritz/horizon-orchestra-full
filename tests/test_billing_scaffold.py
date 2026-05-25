"""Tests for BillingScaffold (dev-mode, no Stripe API key required)."""

from __future__ import annotations

import asyncio
import json
import time
import unittest
from datetime import datetime, timezone

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)


class BillingScaffoldDevModeTests(unittest.TestCase):
    """All tests operate in dev mode (stripe_api_key="")."""

    def setUp(self):
        from orchestra.billing.scaffold import BillingScaffold, ScaffoldConfig
        self.config = ScaffoldConfig()
        self.scaffold = BillingScaffold(self.config)

    def tearDown(self):
        loop.run_until_complete(self.scaffold.close())

    # ── Customer management ──────────────────────────────────────────────

    def test_ensure_customer_creates_local_record(self):
        result = loop.run_until_complete(
            self.scaffold.ensure_customer("user-1", "a@b.com", "Alice")
        )
        self.assertIn("id", result)
        self.assertTrue(result["id"].startswith("cus_dev_"))
        self.assertEqual(result["email"], "a@b.com")
        self.assertEqual(self.scaffold.get_customer_id("user-1"), result["id"])

    def test_ensure_customer_returns_existing(self):
        cid = loop.run_until_complete(
            self.scaffold.ensure_customer("user-2", "b@c.com", "Bob")
        )["id"]
        result2 = loop.run_until_complete(
            self.scaffold.ensure_customer("user-2", "b@c.com", "Bob")
        )
        self.assertEqual(result2["id"], cid)

    def test_get_customer_id_nonexistent(self):
        self.assertIsNone(self.scaffold.get_customer_id("no-such-user"))

    # ── Subscription lifecycle ───────────────────────────────────────────

    def test_create_subscription_free_tier(self):
        loop.run_until_complete(
            self.scaffold.ensure_customer("sub-user", "sub@x.com", "Sub")
        )
        sub = loop.run_until_complete(
            self.scaffold.create_subscription("sub-user", "free")
        )
        self.assertEqual(sub.user_id, "sub-user")
        self.assertEqual(sub.tier, "free")
        self.assertEqual(sub.status, "active")
        self.assertEqual(sub.stripe_subscription_id, "")

    def test_create_subscription_pro_tier_in_dev_mode(self):
        sub = loop.run_until_complete(
            self.scaffold.create_subscription("dev-pro", "pro")
        )
        self.assertEqual(sub.tier, "pro")
        self.assertEqual(sub.status, "active")

    def test_create_subscription_team_tier_in_dev_mode(self):
        sub = loop.run_until_complete(
            self.scaffold.create_subscription("dev-team", "team")
        )
        self.assertEqual(sub.tier, "team")

    def test_create_subscription_max_tier_in_dev_mode(self):
        sub = loop.run_until_complete(
            self.scaffold.create_subscription("dev-max", "max")
        )
        self.assertEqual(sub.tier, "max")

    def test_get_subscription_returns_none_for_unknown(self):
        sub = loop.run_until_complete(self.scaffold.get_subscription("no-one"))
        self.assertIsNone(sub)

    def test_get_subscription_returns_cached(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("get-me", "pro")
        )
        sub = loop.run_until_complete(self.scaffold.get_subscription("get-me"))
        self.assertIsNotNone(sub)
        self.assertEqual(sub.tier, "pro")

    def test_cancel_subscription_no_subscription(self):
        result = loop.run_until_complete(
            self.scaffold.cancel_subscription("no-one")
        )
        self.assertEqual(result["status"], "no_subscription")

    def test_cancel_subscription_dev_mode(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("cancel-me", "pro")
        )
        result = loop.run_until_complete(
            self.scaffold.cancel_subscription("cancel-me")
        )
        self.assertEqual(result["status"], "canceled")
        sub = loop.run_until_complete(
            self.scaffold.get_subscription("cancel-me")
        )
        self.assertEqual(sub.tier, "free")

    def test_cancel_subscription_immediate_dev_mode(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("cancel-me2", "team")
        )
        result = loop.run_until_complete(
            self.scaffold.cancel_subscription("cancel-me2", immediately=True)
        )
        self.assertEqual(result["status"], "canceled")

    def test_change_tier_creates_if_no_subscription(self):
        result = loop.run_until_complete(
            self.scaffold.change_tier("new-user", "pro")
        )
        self.assertEqual(result["status"], "created")
        self.assertEqual(result["tier"], "pro")

    def test_change_tier_dev_mode(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("change-me", "free")
        )
        result = loop.run_until_complete(
            self.scaffold.change_tier("change-me", "max")
        )
        self.assertEqual(result["status"], "changed")
        self.assertEqual(result["tier"], "max")
        sub = loop.run_until_complete(
            self.scaffold.get_subscription("change-me")
        )
        self.assertEqual(sub.tier, "max")

    # ── Usage metering ───────────────────────────────────────────────────

    def test_record_usage_creates_record(self):
        meter = loop.run_until_complete(
            self.scaffold.record_usage("usage-user", requests=10, tokens=500)
        )
        self.assertEqual(meter.user_id, "usage-user")
        self.assertEqual(meter.requests_used, 10)
        self.assertEqual(meter.tokens_used, 500)

    def test_record_usage_increments(self):
        loop.run_until_complete(
            self.scaffold.record_usage("inc-user", requests=5)
        )
        meter = loop.run_until_complete(
            self.scaffold.record_usage("inc-user", requests=3, tokens=100)
        )
        self.assertEqual(meter.requests_used, 8)
        self.assertEqual(meter.tokens_used, 100)

    def test_record_usage_all_fields(self):
        meter = loop.run_until_complete(
            self.scaffold.record_usage(
                "all-user", requests=1, tokens=2, agents=3,
                storage_mb=4.5, tool_calls=6, sessions=7,
            )
        )
        self.assertEqual(meter.requests_used, 1)
        self.assertEqual(meter.tokens_used, 2)
        self.assertEqual(meter.agents_spawned, 3)
        self.assertAlmostEqual(meter.storage_used_mb, 4.5)
        self.assertEqual(meter.tool_calls_used, 6)
        self.assertEqual(meter.sessions_used, 7)

    def test_check_limits_allowed_when_within_limits(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("limit-user", "pro")
        )
        result = loop.run_until_complete(
            self.scaffold.check_limits("limit-user")
        )
        self.assertTrue(result["allowed"])
        self.assertEqual(result["reason"], "Within limits")

    def test_check_limits_exceeded(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("exceed-user", "free")
        )
        loop.run_until_complete(
            self.scaffold.record_usage("exceed-user", requests=999_999)
        )
        result = loop.run_until_complete(
            self.scaffold.check_limits("exceed-user")
        )
        self.assertFalse(result["allowed"])
        self.assertIn("Daily request limit reached", result["reason"])

    def test_check_limits_unknown_user_uses_default_tier(self):
        result = loop.run_until_complete(
            self.scaffold.check_limits("stranger")
        )
        self.assertTrue(result["allowed"])

    def test_report_usage_snapshot(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("snap-user", "team")
        )
        loop.run_until_complete(
            self.scaffold.record_usage("snap-user", requests=42, tokens=999)
        )
        snap = loop.run_until_complete(
            self.scaffold.report_usage_snapshot("snap-user")
        )
        self.assertEqual(snap["user_id"], "snap-user")
        self.assertEqual(snap["tier"], "team")
        self.assertEqual(snap["requests_used"], 42)
        self.assertEqual(snap["tokens_used"], 999)

    # ── Entitlement checks ───────────────────────────────────────────────

    def test_check_entitlement_free_cannot_use_advanced_arch(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("ent-user", "free")
        )
        result = loop.run_until_complete(
            self.scaffold.check_entitlement("ent-user", architecture="C")
        )
        self.assertFalse(result["allowed"])
        self.assertIn("not available", result["reason"])

    def test_check_entitlement_free_can_use_arch_a(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("ent-user2", "free")
        )
        result = loop.run_until_complete(
            self.scaffold.check_entitlement("ent-user2", architecture="A")
        )
        self.assertTrue(result["allowed"])

    def test_check_entitlement_model_access(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("model-user", "pro")
        )
        result = loop.run_until_complete(
            self.scaffold.check_entitlement("model-user", model="gpt-4o")
        )
        self.assertTrue(result["allowed"])

    def test_check_entitlement_model_denied(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("model-user2", "free")
        )
        result = loop.run_until_complete(
            self.scaffold.check_entitlement("model-user2", model="gpt-4o")
        )
        self.assertFalse(result["allowed"])

    def test_check_entitlement_feature_access(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("feat-user", "max")
        )
        result = loop.run_until_complete(
            self.scaffold.check_entitlement("feat-user", feature="Unlimited requests")
        )
        self.assertTrue(result["allowed"])

    def test_check_entitlement_feature_denied(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("feat-user2", "free")
        )
        result = loop.run_until_complete(
            self.scaffold.check_entitlement("feat-user2", feature="500 GB storage")
        )
        self.assertFalse(result["allowed"])

    def test_check_entitlement_no_args_passes(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("any-user", "free")
        )
        result = loop.run_until_complete(
            self.scaffold.check_entitlement("any-user")
        )
        self.assertTrue(result["allowed"])

    def test_check_entitlement_unknown_user_uses_default_tier(self):
        result = loop.run_until_complete(
            self.scaffold.check_entitlement("ghost", model="gpt-4o-mini")
        )
        self.assertTrue(result["allowed"])

    # ── Checkout & portal sessions ───────────────────────────────────────

    def test_create_checkout_session_dev_mode(self):
        result = loop.run_until_complete(
            self.scaffold.create_checkout_session(
                "checkout-user", "pro",
                success_url="https://example.com/success",
                cancel_url="https://example.com/cancel",
            )
        )
        self.assertIn("id", result)
        self.assertTrue(result["id"].startswith("cs_dev_"))
        self.assertEqual(result["url"], "https://example.com/success")

    def test_create_portal_session_dev_mode(self):
        result = loop.run_until_complete(
            self.scaffold.create_portal_session(
                "portal-user", return_url="https://example.com/portal"
            )
        )
        self.assertEqual(result["id"], "ps_dev")
        self.assertEqual(result["url"], "https://example.com/portal")

    def test_create_portal_session_with_customer(self):
        loop.run_until_complete(
            self.scaffold.ensure_customer("portal-user2", "p@x.com", "Portal")
        )
        result = loop.run_until_complete(
            self.scaffold.create_portal_session(
                "portal-user2", return_url="https://example.com/portal"
            )
        )
        self.assertEqual(result["id"], "ps_dev")

    # ── Invoices ─────────────────────────────────────────────────────────

    def test_get_invoices_dev_mode_returns_empty(self):
        invoices = loop.run_until_complete(
            self.scaffold.get_invoices("inv-user")
        )
        self.assertEqual(invoices, [])

    def test_get_invoices_with_customer_dev_mode(self):
        loop.run_until_complete(
            self.scaffold.ensure_customer("inv-user2", "i@x.com", "Inv")
        )
        invoices = loop.run_until_complete(
            self.scaffold.get_invoices("inv-user2")
        )
        self.assertEqual(invoices, [])

    # ── Webhook handling ─────────────────────────────────────────────────

    def test_handle_webhook_invalid_json(self):
        result = loop.run_until_complete(
            self.scaffold.handle_webhook(b"not json", "")
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid JSON", result["message"])

    def test_handle_webhook_unhandled_event(self):
        payload = json.dumps({"type": "unknown.event", "data": {"object": {}}})
        result = loop.run_until_complete(
            self.scaffold.handle_webhook(payload.encode(), "")
        )
        self.assertEqual(result["status"], "ignored")
        self.assertEqual(result["event_type"], "unknown.event")

    def test_handle_webhook_invoice_paid_resets_usage(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("webhook-user", "pro")
        )
        loop.run_until_complete(
            self.scaffold.record_usage("webhook-user", requests=100)
        )
        snap_before = loop.run_until_complete(
            self.scaffold.report_usage_snapshot("webhook-user")
        )
        self.assertEqual(snap_before["requests_used"], 100)

        payload = json.dumps({
            "type": "invoice.paid",
            "data": {
                "object": {
                    "customer": self.scaffold._customer_map.get("webhook-user", ""),
                }
            },
        })
        result = loop.run_until_complete(
            self.scaffold.handle_webhook(payload.encode(), "")
        )
        self.assertEqual(result["status"], "ok")
        snap_after = loop.run_until_complete(
            self.scaffold.report_usage_snapshot("webhook-user")
        )
        self.assertEqual(snap_after["requests_used"], 0)

    def test_handle_webhook_subscription_deleted(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("del-user", "team")
        )
        sub_before = loop.run_until_complete(
            self.scaffold.get_subscription("del-user")
        )
        self.assertEqual(sub_before.tier, "team")

        payload = json.dumps({
            "type": "customer.subscription.deleted",
            "data": {
                "object": {
                    "id": sub_before.stripe_subscription_id,
                }
            },
        })
        result = loop.run_until_complete(
            self.scaffold.handle_webhook(payload.encode(), "")
        )
        self.assertEqual(result["status"], "ok")
        sub_after = loop.run_until_complete(
            self.scaffold.get_subscription("del-user")
        )
        self.assertEqual(sub_after.status, "canceled")
        self.assertEqual(sub_after.tier, "free")

    def test_handle_webhook_subscription_updated(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("upd-user", "pro")
        )
        sub_before = loop.run_until_complete(
            self.scaffold.get_subscription("upd-user")
        )

        payload = json.dumps({
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "id": sub_before.stripe_subscription_id,
                    "status": "past_due",
                    "cancel_at_period_end": True,
                    "current_period_start": time.time(),
                    "current_period_end": time.time() + 2592000,
                }
            },
        })
        result = loop.run_until_complete(
            self.scaffold.handle_webhook(payload.encode(), "")
        )
        self.assertEqual(result["status"], "ok")
        sub_after = loop.run_until_complete(
            self.scaffold.get_subscription("upd-user")
        )
        self.assertEqual(sub_after.status, "past_due")
        self.assertTrue(sub_after.cancel_at_period_end)

    def test_handle_webhook_payment_failed(self):
        loop.run_until_complete(
            self.scaffold.create_subscription("payfail-user", "pro")
        )
        sub_before = loop.run_until_complete(
            self.scaffold.get_subscription("payfail-user")
        )

        payload = json.dumps({
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": sub_before.stripe_subscription_id,
                }
            },
        })
        result = loop.run_until_complete(
            self.scaffold.handle_webhook(payload.encode(), "")
        )
        self.assertEqual(result["status"], "ok")
        sub_after = loop.run_until_complete(
            self.scaffold.get_subscription("payfail-user")
        )
        self.assertEqual(sub_after.status, "past_due")

    def test_handle_webhook_checkout_completed(self):
        loop.run_until_complete(
            self.scaffold.ensure_customer("chk-user", "chk@x.com", "Checkout")
        )
        payload = json.dumps({
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "metadata": {"user_id": "chk-user", "tier": "pro"},
                    "customer": self.scaffold._customer_map.get("chk-user", ""),
                    "subscription": "",
                }
            },
        })
        result = loop.run_until_complete(
            self.scaffold.handle_webhook(payload.encode(), "")
        )
        self.assertEqual(result["status"], "ok")

    # ── Tier info queries ────────────────────────────────────────────────

    def test_get_tier_info(self):
        info = self.scaffold.get_tier_info("free")
        self.assertEqual(info["name"], "free")
        self.assertIn("limits", info)
        self.assertIn("features", info)

    def test_get_tier_info_canonicalizes(self):
        info = self.scaffold.get_tier_info("maker")
        self.assertEqual(info["name"], "free")

    def test_list_tiers_returns_four(self):
        tiers = self.scaffold.list_tiers()
        self.assertEqual(len(tiers), 4)
        names = [t["name"] for t in tiers]
        self.assertEqual(names, ["free", "pro", "team", "max"])

    # ── Tier translation ─────────────────────────────────────────────────

    def test_tier_translation_canonical_free(self):
        from orchestra.billing.scaffold import _canonical
        self.assertEqual(_canonical("free"), "free")
        self.assertEqual(_canonical("maker"), "free")

    def test_tier_translation_canonical_pro(self):
        from orchestra.billing.scaffold import _canonical
        self.assertEqual(_canonical("pro"), "pro")
        self.assertEqual(_canonical("builder"), "pro")

    def test_tier_translation_canonical_team(self):
        from orchestra.billing.scaffold import _canonical
        self.assertEqual(_canonical("team"), "team")

    def test_tier_translation_canonical_max(self):
        from orchestra.billing.scaffold import _canonical
        self.assertEqual(_canonical("max"), "max")
        self.assertEqual(_canonical("enterprise"), "max")

    def test_tier_translation_unknown_passthrough(self):
        from orchestra.billing.scaffold import _canonical
        self.assertEqual(_canonical("unknown"), "unknown")

    # ── Webhook signature verification ───────────────────────────────────

    def test_verify_webhook_signature_no_secret(self):
        payload = json.dumps({"type": "test"})
        result = loop.run_until_complete(
            self.scaffold.handle_webhook(payload.encode(), "any_sig")
        )
        self.assertEqual(result["status"], "ignored")

    def test_verify_webhook_signature_valid(self):
        from orchestra.billing.scaffold import ScaffoldConfig, BillingScaffold
        secret = "whsec_test_secret"
        cfg = ScaffoldConfig(stripe_webhook_secret=secret)
        s = BillingScaffold(cfg)
        payload = json.dumps({"type": "test.event", "data": {"object": {}}})
        timestamp = str(int(time.time()))
        import hashlib, hmac
        signed_payload = f"{timestamp}.{payload}"
        expected_sig = hmac.new(
            secret.encode(), signed_payload.encode(), hashlib.sha256
        ).hexdigest()
        signature = f"t={timestamp},v1={expected_sig}"
        result = loop.run_until_complete(
            s.handle_webhook(payload.encode(), signature)
        )
        self.assertEqual(result["status"], "ignored")
        loop.run_until_complete(s.close())

    def test_verify_webhook_signature_invalid(self):
        from orchestra.billing.scaffold import ScaffoldConfig, BillingScaffold
        secret = "whsec_test_secret"
        cfg = ScaffoldConfig(stripe_webhook_secret=secret)
        s = BillingScaffold(cfg)
        payload = json.dumps({"type": "test.event", "data": {"object": {}}})
        signature = "t=1234567890,v1=bad_signature"
        result = loop.run_until_complete(
            s.handle_webhook(payload.encode(), signature)
        )
        self.assertEqual(result["status"], "error")
        self.assertIn("signature", result.get("message", "").lower())
        loop.run_until_complete(s.close())

    # ── ScaffoldConfig defaults ──────────────────────────────────────────

    def test_scaffold_config_defaults(self):
        from orchestra.billing.scaffold import ScaffoldConfig
        cfg = ScaffoldConfig()
        self.assertEqual(cfg.stripe_api_key, "")
        self.assertEqual(cfg.currency, "usd")
        self.assertEqual(cfg.default_tier, "free")
        self.assertTrue(cfg.enable_free_tier)
        self.assertIn("free", cfg.stripe_price_ids)
        self.assertIn("pro", cfg.stripe_price_ids)
        self.assertIn("team", cfg.usage_limits)
        self.assertIn("max", cfg.usage_limits)

    def test_scaffold_config_usage_limit_values(self):
        from orchestra.billing.scaffold import ScaffoldConfig
        cfg = ScaffoldConfig()
        free_limits = cfg.usage_limits["free"]
        self.assertEqual(free_limits["max_requests_per_day"], 50)
        max_limits = cfg.usage_limits["max"]
        self.assertEqual(max_limits["max_requests_per_day"], -1)

    # ── Edge cases ───────────────────────────────────────────────────────

    def test_multiple_users_independent_state(self):
        loop.run_until_complete(
            self.scaffold.ensure_customer("alice", "a@x.com", "Alice")
        )
        loop.run_until_complete(
            self.scaffold.ensure_customer("bob", "b@x.com", "Bob")
        )
        loop.run_until_complete(
            self.scaffold.create_subscription("alice", "pro")
        )
        loop.run_until_complete(
            self.scaffold.create_subscription("bob", "free")
        )
        loop.run_until_complete(
            self.scaffold.record_usage("alice", requests=10)
        )
        snap_alice = loop.run_until_complete(
            self.scaffold.report_usage_snapshot("alice")
        )
        snap_bob = loop.run_until_complete(
            self.scaffold.report_usage_snapshot("bob")
        )
        self.assertEqual(snap_alice["requests_used"], 10)
        self.assertEqual(snap_bob["requests_used"], 0)
        self.assertEqual(snap_alice["tier"], "pro")
        self.assertEqual(snap_bob["tier"], "free")

    def test_close_twice(self):
        loop.run_until_complete(self.scaffold.close())
        loop.run_until_complete(self.scaffold.close())

    def test_ensure_customer_get_customer_id(self):
        loop.run_until_complete(
            self.scaffold.ensure_customer("lookup-user", "l@x.com", "Lookup")
        )
        cid = self.scaffold.get_customer_id("lookup-user")
        self.assertIsNotNone(cid)
        self.assertTrue(cid.startswith("cus_dev_"))


if __name__ == "__main__":
    unittest.main()
