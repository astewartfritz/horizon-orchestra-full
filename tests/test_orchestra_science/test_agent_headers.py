from __future__ import annotations

import time
import unittest

from orchestra.code_agent.agent_headers.context import ContextManager, generate_context_id
from orchestra.code_agent.agent_headers.freshness import (
    FreshnessTracker,
    StalenessPolicy,
    get_last_updated,
    set_last_updated,
)
from orchestra.code_agent.agent_headers.identity import (
    AgentType,
    HumanVsAIPolicy,
    parse_agent_type,
)
from orchestra.code_agent.agent_headers.intent import Intent, IntentRouter, parse_intent
from orchestra.code_agent.agent_headers.middleware import (
    AgentHeadersMiddleware,
    register_agent_headers_middleware,
)
from orchestra.code_agent.agent_headers.models import (
    AgentRole,
    AgentTokenClaims,
    RateLimitPolicy,
)
from orchestra.code_agent.agent_headers.ratelimit import (
    RateLimitStore,
    parse_error_recovery,
)
from orchestra.code_agent.agent_headers.role import RolePolicy, parse_agent_role
from orchestra.code_agent.agent_headers.tokens import (
    AgentTokenManager,
    parse_agent_token,
)


# ── Context IDs (a) ─────────────────────────────────────────────────────

class TestContextIds(unittest.TestCase):

    def setUp(self):
        self.mgr = ContextManager()

    def test_generate_context_id_returns_unique(self):
        ids = {generate_context_id() for _ in range(100)}
        self.assertEqual(len(ids), 100)

    def test_create_and_get_context(self):
        ctx_id = self.mgr.create_context({"user": "alice"})
        record = self.mgr.get_context(ctx_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.data["user"], "alice")

    def test_get_nonexistent_context(self):
        self.assertIsNone(self.mgr.get_context("nope"))

    def test_update_context(self):
        ctx_id = self.mgr.create_context({"step": 1})
        self.assertTrue(self.mgr.update_context(ctx_id, {"step": 2}))
        record = self.mgr.get_context(ctx_id)
        self.assertEqual(record.data["step"], 2)
        self.assertEqual(record.turn_count, 1)

    def test_update_nonexistent_context(self):
        self.assertFalse(self.mgr.update_context("nope", {"x": 1}))

    def test_delete_context(self):
        ctx_id = self.mgr.create_context()
        self.assertTrue(self.mgr.delete_context(ctx_id))
        self.assertIsNone(self.mgr.get_context(ctx_id))

    def test_delete_nonexistent(self):
        self.assertFalse(self.mgr.delete_context("nope"))

    def test_expired_context(self):
        mgr = ContextManager(default_ttl=-1)
        ctx_id = mgr.create_context()
        self.assertIsNone(mgr.get_context(ctx_id))

    def test_extract_from_headers(self):
        ctx_id = self.mgr.create_context()
        headers = {"X-Agent-Context-Id": ctx_id}
        self.assertEqual(self.mgr.extract_from_headers(headers), ctx_id)

    def test_extract_from_headers_missing(self):
        self.assertIsNone(self.mgr.extract_from_headers({}))

    def test_header_name(self):
        self.assertEqual(ContextManager.header_name(), "X-Agent-Context-Id")

    def test_update_increments_turn_count(self):
        ctx_id = self.mgr.create_context()
        self.mgr.update_context(ctx_id, {"a": 1})
        self.mgr.update_context(ctx_id, {"b": 2})
        record = self.mgr.get_context(ctx_id)
        self.assertEqual(record.turn_count, 2)

    def test_context_eviction(self):
        mgr = ContextManager(default_ttl=0)
        ctx_id = mgr.create_context()
        time.sleep(0.01)
        self.assertIsNone(mgr.get_context(ctx_id))


# ── Intent-Based Headers (b) ─────────────────────────────────────────────

class TestIntentHeaders(unittest.TestCase):

    def test_parse_intent_known(self):
        headers = {"X-Agent-Intent": "order_status_check"}
        self.assertEqual(parse_intent(headers), Intent.ORDER_STATUS_CHECK)

    def test_parse_intent_case_insensitive(self):
        headers = {"x-agent-intent": "DATA_QUERY"}
        self.assertEqual(parse_intent(headers), Intent.DATA_QUERY)

    def test_parse_intent_unknown_returns_unknown(self):
        headers = {"X-Agent-Intent": "garbage"}
        self.assertEqual(parse_intent(headers), Intent.UNKNOWN)

    def test_parse_intent_missing_returns_unknown(self):
        self.assertEqual(parse_intent({}), Intent.UNKNOWN)

    def test_intent_router_dispatch(self):
        router = IntentRouter()
        results = []
        router.register(Intent.ORDER_STATUS_CHECK, lambda: results.append("called"))
        router.dispatch(Intent.ORDER_STATUS_CHECK)
        self.assertEqual(results, ["called"])

    def test_intent_router_missing_handler(self):
        router = IntentRouter()
        with self.assertRaises(KeyError):
            router.dispatch(Intent.ORDER_STATUS_CHECK)

    def test_intent_router_unknown_fallback(self):
        router = IntentRouter()
        results = []
        router.register(Intent.UNKNOWN, lambda: results.append("fallback"))
        router.dispatch(Intent.DATA_QUERY)
        self.assertEqual(results, ["fallback"])

    def test_intent_router_has_handler(self):
        router = IntentRouter()
        router.register(Intent.ANALYSIS, lambda: None)
        self.assertTrue(router.has_handler(Intent.ANALYSIS))
        self.assertFalse(router.has_handler(Intent.DATA_QUERY))

    def test_header_name(self):
        self.assertEqual(IntentRouter.header_name(), "X-Agent-Intent")


# ── Agent Role Identifiers (c) ───────────────────────────────────────────

class TestAgentRole(unittest.TestCase):

    def test_parse_role_known(self):
        headers = {"X-Agent-Role": "customer_service"}
        self.assertEqual(parse_agent_role(headers), AgentRole.CUSTOMER_SERVICE)

    def test_parse_role_case_insensitive(self):
        headers = {"x-agent-role": "ANALYTICS"}
        self.assertEqual(parse_agent_role(headers), AgentRole.ANALYTICS)

    def test_parse_role_unknown_returns_system(self):
        headers = {"X-Agent-Role": "hacker"}
        self.assertEqual(parse_agent_role(headers), AgentRole.SYSTEM)

    def test_parse_role_missing_returns_system(self):
        self.assertEqual(parse_agent_role({}), AgentRole.SYSTEM)

    def test_role_policy_get_config(self):
        policy = RolePolicy()
        cfg = policy.get_config(AgentRole.CUSTOMER_SERVICE)
        self.assertEqual(cfg["verbosity"], "low")
        self.assertFalse(cfg["include_internal_ids"])

    def test_role_policy_set_config(self):
        policy = RolePolicy()
        custom = {"verbosity": "minimal", "include_internal_ids": False}
        policy.set_config(AgentRole.DEVELOPER, custom)
        self.assertEqual(policy.get_config(AgentRole.DEVELOPER), custom)

    def test_role_policy_unknown_role_defaults_to_system(self):
        policy = RolePolicy()
        cfg = policy.get_config(AgentRole.SYSTEM)
        self.assertEqual(cfg["verbosity"], "normal")

    def test_header_name(self):
        self.assertEqual(RolePolicy.header_name(), "X-Agent-Role")


# ── Human vs AI Differentiation (d) ──────────────────────────────────────

class TestHumanVsAI(unittest.TestCase):

    def test_parse_agent_type_ai(self):
        headers = {"X-Agent-Type": "ai"}
        self.assertEqual(parse_agent_type(headers), AgentType.AI)

    def test_parse_agent_type_human(self):
        headers = {"X-Agent-Type": "human"}
        self.assertEqual(parse_agent_type(headers), AgentType.HUMAN)

    def test_parse_agent_type_case_insensitive(self):
        headers = {"x-agent-type": "HYBRID"}
        self.assertEqual(parse_agent_type(headers), AgentType.HYBRID)

    def test_parse_agent_type_unknown_returns_human(self):
        headers = {"X-Agent-Type": "robot"}
        self.assertEqual(parse_agent_type(headers), AgentType.HUMAN)

    def test_parse_agent_type_missing_returns_human(self):
        self.assertEqual(parse_agent_type({}), AgentType.HUMAN)

    def test_human_vs_ai_policy_ai_has_higher_rate_limit(self):
        policy = HumanVsAIPolicy()
        ai_policy = policy.get_policy(AgentType.AI)
        human_policy = policy.get_policy(AgentType.HUMAN)
        self.assertGreater(ai_policy["max_requests_per_min"], human_policy["max_requests_per_min"])

    def test_human_vs_ai_policy_ai_requires_audit(self):
        policy = HumanVsAIPolicy()
        self.assertTrue(policy.get_policy(AgentType.AI)["require_audit"])
        self.assertFalse(policy.get_policy(AgentType.HUMAN)["require_audit"])

    def test_human_vs_ai_policy_set_custom(self):
        policy = HumanVsAIPolicy()
        policy.set_policy(AgentType.AI, {"max_requests_per_min": 999})
        self.assertEqual(policy.get_policy(AgentType.AI)["max_requests_per_min"], 999)

    def test_header_name(self):
        self.assertEqual(HumanVsAIPolicy.header_name(), "X-Agent-Type")


# ── Token Claims for Agent Verification (e) ──────────────────────────────

class TestAgentTokens(unittest.TestCase):

    def setUp(self):
        self.mgr = AgentTokenManager(secret="test-secret-key-1234567890")

    def test_parse_agent_token_from_header(self):
        headers = {"X-Agent-Token": "my-token"}
        self.assertEqual(parse_agent_token(headers), "my-token")

    def test_parse_agent_token_missing(self):
        self.assertEqual(parse_agent_token({}), "")

    def test_issue_and_verify_token(self):
        claims = AgentTokenClaims(
            agent_id="agent-1",
            agent_role=AgentRole.ANALYTICS,
            agent_type=AgentType.AI,
            permissions=["read", "write"],
        )
        token = self.mgr.issue_token(claims)
        verified = self.mgr.verify_token(token)
        self.assertIsNotNone(verified)
        self.assertEqual(verified.agent_id, "agent-1")
        self.assertEqual(verified.agent_role, AgentRole.ANALYTICS)
        self.assertEqual(verified.agent_type, AgentType.AI)
        self.assertEqual(verified.permissions, ["read", "write"])

    def test_verify_expired_token(self):
        claims = AgentTokenClaims(
            agent_id="agent-2",
            expires_at=time.time() - 10,
        )
        token = self.mgr.issue_token(claims)
        self.assertIsNone(self.mgr.verify_token(token))

    def test_verify_tampered_token(self):
        claims = AgentTokenClaims(agent_id="agent-3")
        token = self.mgr.issue_token(claims)
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
        self.assertIsNone(self.mgr.verify_token(tampered))

    def test_verify_malformed_token(self):
        self.assertIsNone(self.mgr.verify_token("not-a-token"))

    def test_verify_token_wrong_secret(self):
        mgr2 = AgentTokenManager(secret="different-secret")
        claims = AgentTokenClaims(agent_id="agent-4")
        token = self.mgr.issue_token(claims)
        self.assertIsNone(mgr2.verify_token(token))

    def test_verify_empty_token(self):
        self.assertIsNone(self.mgr.verify_token(""))

    def test_token_defaults(self):
        claims = AgentTokenClaims(agent_id="agent-5")
        self.assertEqual(claims.permissions, ["read"])
        self.assertEqual(claims.agent_role, AgentRole.SYSTEM)
        self.assertEqual(claims.agent_type, AgentType.AI)

    def test_token_owner_and_purpose(self):
        claims = AgentTokenClaims(
            agent_id="agent-6",
            owner_id="user-x",
            purpose="order_check",
        )
        token = self.mgr.issue_token(claims)
        verified = self.mgr.verify_token(token)
        self.assertEqual(verified.owner_id, "user-x")
        self.assertEqual(verified.purpose, "order_check")


# ── Timestamp Metadata for Data Freshness (f) ───────────────────────────

class TestDataFreshness(unittest.TestCase):

    def setUp(self):
        self.tracker = FreshnessTracker()

    def test_get_last_updated_nonexistent(self):
        self.assertIsNone(get_last_updated("nonexistent_resource_xyz"))

    def test_set_and_get_last_updated(self):
        set_last_updated("orders", 1000.0)
        self.assertEqual(get_last_updated("orders"), 1000.0)

    def test_set_last_updated_default(self):
        set_last_updated("products")
        ts = get_last_updated("products")
        self.assertIsNotNone(ts)
        self.assertGreater(ts, 0)

    def test_is_fresh_within_policy(self):
        self.tracker.register_resource("orders", StalenessPolicy(max_age_seconds=300))
        set_last_updated("orders", time.time())
        self.assertTrue(self.tracker.is_fresh("orders"))

    def test_is_not_fresh_stale(self):
        self.tracker.register_resource("orders", StalenessPolicy(max_age_seconds=1))
        set_last_updated("orders", time.time() - 10)
        self.assertFalse(self.tracker.is_fresh("orders"))

    def test_is_fresh_with_explicit_staleness(self):
        set_last_updated("orders", time.time() - 5)
        self.assertTrue(self.tracker.is_fresh("orders", staleness_seconds=10))

    def test_is_fresh_no_resource_record(self):
        self.assertFalse(self.tracker.is_fresh("nonexistent"))

    def test_parse_staleness_accept(self):
        headers = {"X-Data-Staleness-Accept": "30"}
        self.assertEqual(self.tracker.parse_staleness_accept(headers), 30.0)

    def test_parse_staleness_accept_missing(self):
        self.assertEqual(self.tracker.parse_staleness_accept({}), 0.0)

    def test_parse_staleness_accept_invalid(self):
        headers = {"X-Data-Staleness-Accept": "abc"}
        self.assertEqual(self.tracker.parse_staleness_accept(headers), 0.0)

    def test_format_last_updated_header(self):
        set_last_updated("orders", 1000000.0)
        result = self.tracker.format_last_updated_header("orders")
        self.assertIn("GMT", result)

    def test_header_names(self):
        self.assertEqual(FreshnessTracker.last_updated_header(), "X-Data-LastUpdated")
        self.assertEqual(FreshnessTracker.staleness_header(), "X-Data-Staleness-Accept")


# ── Rate-Limit and Error Recovery Headers (g) ──────────────────────────

class TestRateLimitAndRecovery(unittest.TestCase):

    def setUp(self):
        self.store = RateLimitStore()

    def test_check_allows_first_request(self):
        result = self.store.check("agent-1")
        self.assertEqual(result["allowed"], 1)

    def test_check_reduces_remaining(self):
        for _ in range(3):
            self.store.check("agent-2")
        result = self.store.check("agent-2")
        self.assertGreater(result["limit"], result["remaining"])

    def test_check_blocks_excessive_requests(self):
        policy = RateLimitPolicy(requests_per_minute=2, requests_per_hour=1000)
        for _ in range(2):
            self.store.check("agent-3", policy)
        result = self.store.check("agent-3", policy)
        self.assertEqual(result["allowed"], 0)
        self.assertEqual(result["remaining"], 0)

    def test_format_headers(self):
        result = {"allowed": 1, "remaining": 45, "reset": 30, "limit": 60}
        headers = self.store.format_headers(result)
        header_dict = dict(headers)
        self.assertEqual(header_dict["X-RateLimit-Remaining"], "45")
        self.assertEqual(header_dict["X-RateLimit-Reset"], "30")
        self.assertEqual(header_dict["X-RateLimit-Limit"], "60")

    def test_format_error_recovery(self):
        result = self.store.format_error_recovery(60)
        self.assertEqual(result, "RetryAfter=60s")

    def test_parse_error_recovery_retry_after(self):
        headers = {"X-Error-Recovery": "RetryAfter=30s"}
        result = parse_error_recovery(headers)
        self.assertEqual(result["retry_after"], 30)

    def test_parse_error_recovery_case_insensitive(self):
        headers = {"x-error-recovery": "retryafter=120s"}
        result = parse_error_recovery(headers)
        self.assertEqual(result["retry_after"], 120)

    def test_parse_error_recovery_missing(self):
        result = parse_error_recovery({})
        self.assertEqual(result["strategy"], "unknown")

    def test_parse_error_recovery_no_match(self):
        headers = {"X-Error-Recovery": "backoff_exponential"}
        result = parse_error_recovery(headers)
        self.assertEqual(result["strategy"], "backoff_exponential")

    def test_set_policy(self):
        self.store.set_policy("agent-4", RateLimitPolicy(requests_per_minute=10))
        result = self.store.check("agent-4")
        self.assertEqual(result["limit"], 10)

    def test_error_recovery_header_name(self):
        self.assertEqual(RateLimitStore.error_recovery_header(), "X-Error-Recovery")


if __name__ == "__main__":
    unittest.main()
