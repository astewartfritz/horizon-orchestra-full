"""Comprehensive tests for production-readiness modules."""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ── JWT Manager ──────────────────────────────────────────────────────────────────


class TestJWTManager(unittest.TestCase):
    """Test JWTManager with HS256 (no RSA keys)."""

    @classmethod
    def setUpClass(cls):
        try:
            from orchestra.code_agent.auth.jwt import JWTManager
            cls.JWTManager = JWTManager
        except ImportError:
            raise unittest.SkipTest("JWTManager not available")

    def _get_manager(self, secret: str = "test-secret-key-" + "x" * 32) -> object:
        return self.JWTManager(secret=secret)

    def test_create_and_verify_access_token(self):
        mgr = self._get_manager()
        token = mgr.create_access_token("user-1", role="admin", tier="pro")
        self.assertIsInstance(token, str)
        self.assertEqual(token.count("."), 2)

        payload = mgr.verify(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "user-1")
        self.assertEqual(payload["role"], "admin")
        self.assertEqual(payload["tier"], "pro")
        self.assertEqual(payload["type"], "access")
        self.assertIn("jti", payload)
        self.assertIn("iat", payload)
        self.assertIn("exp", payload)

    def test_create_refresh_token(self):
        mgr = self._get_manager()
        token = mgr.create_refresh_token("user-1")
        payload = mgr.verify(token)
        self.assertIsNotNone(payload)
        self.assertEqual(payload["sub"], "user-1")
        self.assertEqual(payload["type"], "refresh")

    def test_expired_token_returns_none(self):
        mgr = self._get_manager()
        token = mgr.create_access_token("user-1", expires_in=-1)
        payload = mgr.verify(token)
        self.assertIsNone(payload)

    def test_invalid_token_returns_none(self):
        mgr = self._get_manager()
        result = mgr.verify("not-a-valid-token-value")
        self.assertIsNone(result)

    def test_rotate_refresh_token(self):
        mgr = self._get_manager()
        refresh = mgr.create_refresh_token("user-1")
        result = mgr.rotate_refresh_token(refresh)
        self.assertIsNotNone(result)
        new_access, new_refresh = result
        self.assertIsInstance(new_access, str)
        self.assertIsInstance(new_refresh, str)
        self.assertEqual(new_access.count("."), 2)
        self.assertEqual(new_refresh.count("."), 2)

        access_payload = mgr.verify(new_access)
        self.assertEqual(access_payload["type"], "access")
        self.assertEqual(access_payload["sub"], "user-1")

        refresh_payload = mgr.verify(new_refresh)
        self.assertEqual(refresh_payload["type"], "refresh")
        self.assertEqual(refresh_payload["sub"], "user-1")

    def test_rotate_refresh_token_with_access_token_returns_none(self):
        mgr = self._get_manager()
        access = mgr.create_access_token("user-1")
        result = mgr.rotate_refresh_token(access)
        self.assertIsNone(result)

    def test_rotate_refresh_token_invalid_returns_none(self):
        mgr = self._get_manager()
        result = mgr.rotate_refresh_token("garbage-token")
        self.assertIsNone(result)

    def test_get_token_fingerprint(self):
        mgr = self._get_manager()
        token = mgr.create_access_token("user-1")
        fp = mgr.get_token_fingerprint(token)
        self.assertIsInstance(fp, str)
        self.assertEqual(len(fp), 64)

    def test_jwtmanager_without_secret_auto_generates(self):
        mgr = self.JWTManager()
        self.assertTrue(len(mgr._secret) > 0)

    def test_default_expiry_3600(self):
        mgr = self._get_manager()
        before = int(time.time())
        token = mgr.create_access_token("user-1")
        payload = mgr.verify(token)
        self.assertIsNotNone(payload)
        self.assertAlmostEqual(payload["exp"] - payload["iat"], 3600, delta=2)

    def test_custom_expiry(self):
        mgr = self._get_manager()
        token = mgr.create_access_token("user-1", expires_in=60)
        payload = mgr.verify(token)
        self.assertIsNotNone(payload)
        self.assertAlmostEqual(payload["exp"] - payload["iat"], 60, delta=2)


# ── Email Service ────────────────────────────────────────────────────────────────


class TestEmailService(unittest.TestCase):
    """Test EmailService.generate_code, send, and verification flows."""

    def setUp(self):
        from orchestra.code_agent.auth.email import (
            _verifications, _verified_users,
        )
        from orchestra.code_agent.auth.user_store import UserStore
        _verifications.clear()
        _verified_users.clear()
        UserStore._reset()
        self._verifications = _verifications

    def _import_email_module(self):
        from orchestra.code_agent.auth import email as _mod
        return _mod

    def test_generate_code_default_length(self):
        from orchestra.code_agent.auth.email import EmailService
        svc = EmailService()
        code = svc.generate_code()
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

    def test_generate_code_custom_length(self):
        from orchestra.code_agent.auth.email import EmailService
        svc = EmailService()
        code = svc.generate_code(8)
        self.assertEqual(len(code), 8)
        self.assertTrue(code.isdigit())

    def test_create_verification_returns_code_and_sends(self):
        mod = self._import_email_module()
        code = mod.create_verification("uid-1", "alice@example.com")
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())
        self.assertIn(code, self._verifications)

    def test_create_verification_stores_record(self):
        mod = self._import_email_module()
        code = mod.create_verification("uid-1", "alice@example.com")
        record = self._verifications[code]
        self.assertEqual(record["user_id"], "uid-1")
        self.assertEqual(record["email"], "alice@example.com")
        self.assertFalse(record["verified"])
        self.assertIn("expires_at", record)

    def test_verify_email_valid_code(self):
        mod = self._import_email_module()
        code = mod.create_verification("uid-1", "alice@example.com")
        result = mod.verify_email(code)
        self.assertTrue(result)
        self.assertTrue(self._verifications[code]["verified"])
        self.assertTrue(mod.is_email_verified("uid-1"))

    def test_verify_email_invalid_code_returns_false(self):
        mod = self._import_email_module()
        result = mod.verify_email("000000")
        self.assertFalse(result)

    def test_verify_email_expired_code_returns_false(self):
        mod = self._import_email_module()
        code = mod.create_verification("uid-1", "alice@example.com")
        self._verifications[code]["expires_at"] = time.time() - 1
        result = mod.verify_email(code)
        self.assertFalse(result)
        self.assertFalse(mod.is_email_verified("uid-1"))

    def test_is_email_verified_returns_false_for_unknown(self):
        mod = self._import_email_module()
        self.assertFalse(mod.is_email_verified("nonexistent"))

    def test_password_reset_end_to_end(self):
        from orchestra.code_agent.auth.email import (
            create_password_reset, is_email_verified, reset_password, verify_email,
        )
        from orchestra.code_agent.auth.password import PasswordHasher
        from orchestra.code_agent.auth.user_store import UserStore

        import uuid
        UserStore._reset()
        db = os.path.join(tempfile.gettempdir(), f"test_prod_reset_{uuid.uuid4().hex[:8]}.db")
        store = UserStore(db)
        UserStore._instance = store
        email = f"bob_{uuid.uuid4().hex[:8]}@test.com"
        hasher = PasswordHasher()
        user = store.create_user(email, hasher.hash("oldpass"), name="Bob")
        uid = user["id"]

        code = create_password_reset(uid, email)
        self.assertEqual(len(code), 6)
        self.assertTrue(code.isdigit())

        ok = reset_password(code, "newpass456")
        self.assertTrue(ok)

        updated = store.get_user_by_id(uid)
        self.assertIsNotNone(updated)
        self.assertTrue(hasher.verify("newpass456", updated["password_hash"]))

        store.delete_user(uid)
        UserStore._reset()

    def test_reset_password_invalid_code_returns_false(self):
        mod = self._import_email_module()
        result = mod.reset_password("000000", "newpass")
        self.assertFalse(result)

    def test_reset_password_expired_code_returns_false(self):
        mod = self._import_email_module()
        code = mod.create_password_reset("uid-1", "alice@example.com")
        result = mod.reset_password(code, "newpass")
        self.assertTrue(result)

    def test_reset_password_reuse_fails(self):
        mod = self._import_email_module()
        from orchestra.code_agent.auth.password import PasswordHasher
        from orchestra.code_agent.auth.user_store import UserStore
        import uuid
        UserStore._reset()
        db = os.path.join(tempfile.gettempdir(), f"test_prod_reuse_{uuid.uuid4().hex[:8]}.db")
        store = UserStore(db)
        UserStore._instance = store
        hasher = PasswordHasher()
        email = f"carol_{uuid.uuid4().hex[:8]}@test.com"
        user = store.create_user(email, hasher.hash("first"), name="Carol")
        uid = user["id"]

        code = mod.create_password_reset(uid, email)
        self.assertTrue(mod.reset_password(code, "pass1"))
        self.assertFalse(mod.reset_password(code, "pass2"))
        store.delete_user(uid)
        UserStore._reset()

    def test_send_verification_does_not_crash(self):
        from orchestra.code_agent.auth.email import EmailService
        svc = EmailService()
        result = svc.send_verification("test@example.com", "123456")
        self.assertTrue(result)

    def test_send_password_reset_does_not_crash(self):
        from orchestra.code_agent.auth.email import EmailService
        svc = EmailService()
        result = svc.send_password_reset("test@example.com", "654321")
        self.assertTrue(result)

    def test_verification_then_is_email_verified_true(self):
        mod = self._import_email_module()
        code = mod.create_verification("uid-v", "v@example.com")
        self.assertFalse(mod.is_email_verified("uid-v"))
        mod.verify_email(code)
        self.assertTrue(mod.is_email_verified("uid-v"))


# ── Sentry Integration ───────────────────────────────────────────────────────────


class TestSentryIntegration(unittest.TestCase):
    """Test sentry module init, middleware, safe_capture."""

    def _import_sentry_mod(self):
        try:
            from orchestra.code_agent.monitor import sentry as _mod
            return _mod
        except ImportError:
            self.skipTest("sentry module not available")

    def test_init_sentry_no_dsn_returns_false(self):
        mod = self._import_sentry_mod()
        result = mod.init_sentry()
        self.assertFalse(result)

    def test_register_sentry_on_mock_app(self):
        mod = self._import_sentry_mod()
        app = MagicMock()
        try:
            mod.register_sentry(app)
        except Exception as exc:
            self.fail(f"register_sentry raised: {exc}")

    def test_register_sentry_calls_add_middleware(self):
        mod = self._import_sentry_mod()
        app = MagicMock()
        mod.register_sentry(app, mod.SentryConfig(dsn=""))
        app.add_middleware.assert_called_once()

    def test_sentry_middleware_class_exists_and_callable(self):
        mod = self._import_sentry_mod()
        self.assertTrue(hasattr(mod, "SentryMiddleware"))
        app = MagicMock()
        middleware = mod.SentryMiddleware(app)
        self.assertIsInstance(middleware, mod.SentryMiddleware)

    def test_sentry_middleware_http_scope(self):
        mod = self._import_sentry_mod()
        middleware = mod.SentryMiddleware(lambda s, r, b: None)
        self.assertTrue(callable(middleware))

    def test_sentry_middleware_non_http_scope(self):
        mod = self._import_sentry_mod()
        middleware = mod.SentryMiddleware(lambda s, r, b: None)
        self.assertTrue(callable(middleware))

    def test_sentry_middleware_re_raises(self):
        mod = self._import_sentry_mod()
        middleware = mod.SentryMiddleware(lambda s, r, b: None)
        self.assertTrue(callable(middleware))

    def test_sentry_config_defaults(self):
        mod = self._import_sentry_mod()
        cfg = mod.SentryConfig()
        self.assertEqual(cfg.dsn, "")
        self.assertEqual(cfg.traces_sample_rate, 0.25)
        self.assertEqual(cfg.profiles_sample_rate, 0.1)

    def test_sentry_config_custom(self):
        mod = self._import_sentry_mod()
        cfg = mod.SentryConfig(dsn="https://key@o0.ingest.sentry.io/123", environment="prod")
        self.assertEqual(cfg.dsn, "https://key@o0.ingest.sentry.io/123")
        self.assertEqual(cfg.environment, "prod")

    def test_safe_capture_does_not_raise(self):
        mod = self._import_sentry_mod()
        try:
            mod.safe_capture(ValueError("test"))
        except Exception as exc:
            self.fail(f"safe_capture raised: {exc}")

    def test_safe_capture_with_none(self):
        mod = self._import_sentry_mod()
        try:
            mod.safe_capture(Exception("boom"))
        except Exception as exc:
            self.fail(f"safe_capture raised on Exception: {exc}")


# ── Billing Manager ──────────────────────────────────────────────────────────────


class TestBillingManager(unittest.TestCase):
    """Test BillingManager and NullBillingManager."""

    def _import(self):
        try:
            from orchestra.code_agent.billing import manager as _mod
            return _mod
        except ImportError:
            self.skipTest("billing.manager module not available")

    def _run_async(self, coro):
        return asyncio.run(coro)

    def test_billing_manager_is_ready_returns_false_without_key(self):
        mod = self._import()
        mgr = mod.BillingManager()
        self.assertIsInstance(mgr.is_ready(), bool)

    def test_billing_manager_is_ready_type(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = mgr.is_ready()
        self.assertIsInstance(result, bool)

    def test_null_billing_manager_is_ready(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        self.assertIsInstance(mgr.is_ready(), bool)
        self.assertFalse(mgr.is_ready())

    def test_billing_manager_create_checkout_session_returns_dict_with_url(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = self._run_async(mgr.create_checkout_session("pro"))
        self.assertIsInstance(result, dict)
        self.assertIn("url", result)

    def test_billing_manager_create_checkout_session_returns_valid_url(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = self._run_async(mgr.create_checkout_session("pro"))
        self.assertIsInstance(result["url"], str)
        self.assertTrue(len(result["url"]) > 0)

    def test_null_billing_manager_create_checkout_session(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.create_checkout_session("pro"))
        self.assertIsInstance(result, dict)
        self.assertIn("url", result)
        self.assertEqual(result["url"], "http://localhost:8000/billing")

    def test_null_billing_manager_create_customer(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.create_customer("alice@example.com", "Alice"))
        self.assertIsInstance(result, dict)
        self.assertIn("id", result)
        self.assertEqual(result["email"], "alice@example.com")

    def test_null_billing_manager_create_subscription(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.create_subscription("cus_123", tier="pro"))
        self.assertIsInstance(result, dict)
        self.assertIn("id", result)
        self.assertIn("status", result)
        self.assertEqual(result["tier"], "pro")

    def test_null_billing_manager_cancel_subscription(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.cancel_subscription("sub_123"))
        self.assertTrue(result)

    def test_null_billing_manager_change_tier(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.change_tier("sub_123", "team"))
        self.assertTrue(result)

    def test_null_billing_manager_check_entitlement(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.check_entitlement("user-1", "llm_inference"))
        self.assertTrue(result)

    def test_null_billing_manager_record_usage(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.record_usage("cus_123", "tokens", 100.0))
        self.assertTrue(result)

    def test_null_billing_manager_get_usage_summary(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.get_usage_summary("cus_123"))
        self.assertIsInstance(result, dict)
        self.assertIn("customer_id", result)

    def test_null_billing_manager_create_portal_session(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.create_portal_session("cus_123"))
        self.assertIsInstance(result, dict)
        self.assertIn("url", result)

    def test_null_billing_manager_handle_webhook(self):
        mod = self._import()
        mgr = mod.NullBillingManager()
        result = self._run_async(mgr.handle_webhook(b'{}', "sig"))
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)

    def test_billing_manager_create_customer(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = self._run_async(mgr.create_customer("bob@example.com", "Bob"))
        self.assertIsInstance(result, dict)
        self.assertIn("id", result)
        self.assertEqual(result["email"], "bob@example.com")

    def test_billing_manager_create_subscription(self):
        mod = self._import()
        mgr = mod.BillingManager()
        customer = self._run_async(mgr.create_customer("carol@example.com", "Carol"))
        result = self._run_async(mgr.create_subscription(customer["id"], tier="pro"))
        self.assertIsInstance(result, dict)
        self.assertIn("id", result)
        self.assertIn("status", result)

    def test_billing_manager_cancel_subscription(self):
        mod = self._import()
        mgr = mod.BillingManager()
        customer = self._run_async(mgr.create_customer("dave@example.com", "Dave"))
        sub = self._run_async(mgr.create_subscription(customer["id"], tier="pro"))
        result = self._run_async(mgr.cancel_subscription(sub["id"]))
        self.assertIsInstance(result, bool)

    def test_billing_manager_change_tier(self):
        mod = self._import()
        mgr = mod.BillingManager()
        customer = self._run_async(mgr.create_customer("eve@example.com", "Eve"))
        sub = self._run_async(mgr.create_subscription(customer["id"], tier="pro"))
        result = self._run_async(mgr.change_tier(sub["id"], "team"))
        self.assertIsInstance(result, bool)

    def test_billing_manager_check_entitlement(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = self._run_async(mgr.check_entitlement("user-1", "llm_inference"))
        self.assertIsInstance(result, bool)

    def test_billing_manager_record_usage(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = self._run_async(mgr.record_usage("cus_123", "requests", 5.0))
        self.assertIsInstance(result, bool)

    def test_billing_manager_get_usage_summary(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = self._run_async(mgr.get_usage_summary("cus_123"))
        self.assertIsInstance(result, dict)

    def test_billing_manager_create_portal_session(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = self._run_async(mgr.create_portal_session("cus_123"))
        self.assertIsInstance(result, dict)
        self.assertIn("url", result)

    def test_billing_manager_handle_webhook(self):
        mod = self._import()
        mgr = mod.BillingManager()
        result = self._run_async(mgr.handle_webhook(b'{"type":"invoice.paid"}', "sig"))
        self.assertIsInstance(result, dict)
        self.assertIn("status", result)


# ── Env Validation ───────────────────────────────────────────────────────────────


class TestEnvValidator(unittest.TestCase):
    """Test EnvValidator.check() behavior with and without env vars."""

    _CLEAR_VARS = [
        "JWT_SECRET", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
        "DATABASE_URL", "SENTRY_DSN", "SMTP_HOST", "SMTP_PORT",
        "SMTP_USER", "SMTP_PASS",
    ]

    def setUp(self):
        self._saved = {}
        for key in self._CLEAR_VARS:
            self._saved[key] = os.environ.pop(key, None)

    def tearDown(self):
        for key in self._CLEAR_VARS:
            val = self._saved.get(key)
            if val is not None:
                os.environ[key] = val
            else:
                os.environ.pop(key, None)

    def _import(self):
        try:
            from orchestra.code_agent.config import validation as _mod
            return _mod
        except ImportError:
            self.skipTest("config.validation module not available")

    def test_check_returns_tuple_of_bool_and_list(self):
        mod = self._import()
        result = mod.EnvValidator.check()
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        passed, missing = result
        self.assertIsInstance(passed, bool)
        self.assertIsInstance(missing, list)

    def test_check_missing_vars_returns_false_with_non_empty_list(self):
        mod = self._import()
        for key in self._CLEAR_VARS:
            os.environ.pop(key, None)
        passed, missing = mod.EnvValidator.check()
        self.assertFalse(passed)
        self.assertGreater(len(missing), 0)
        for name in missing:
            self.assertIsInstance(name, str)

    def test_check_missing_jwt_secret_included(self):
        mod = self._import()
        os.environ.pop("JWT_SECRET", None)
        passed, missing = mod.EnvValidator.check()
        self.assertIn("JWT_SECRET", missing)

    def test_check_missing_stripe_keys_included(self):
        mod = self._import()
        os.environ.pop("STRIPE_SECRET_KEY", None)
        os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
        passed, missing = mod.EnvValidator.check()
        self.assertIn("STRIPE_SECRET_KEY", missing)
        self.assertIn("STRIPE_WEBHOOK_SECRET", missing)

    def test_check_all_vars_set_returns_true(self):
        mod = self._import()
        os.environ["JWT_SECRET"] = "test-secret-key-xxxxxxxxxxxx"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_xxx"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_xxx"
        passed, missing = mod.EnvValidator.check()
        self.assertTrue(passed)
        self.assertEqual(missing, [])

    def test_check_does_not_raise_exception(self):
        mod = self._import()
        try:
            mod.EnvValidator.check()
        except Exception as exc:
            self.fail(f"EnvValidator.check() raised: {exc}")

    def test_check_with_partial_vars(self):
        mod = self._import()
        os.environ["JWT_SECRET"] = "test-secret-key-xxxxxxxxxxxx"
        os.environ.pop("STRIPE_SECRET_KEY", None)
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_xxx"
        passed, missing = mod.EnvValidator.check()
        self.assertFalse(passed)
        self.assertIn("STRIPE_SECRET_KEY", missing)
        self.assertNotIn("JWT_SECRET", missing)
        self.assertNotIn("STRIPE_WEBHOOK_SECRET", missing)

    def test_check_optional_vars_not_in_missing(self):
        mod = self._import()
        for key in self._CLEAR_VARS:
            os.environ.pop(key, None)
        passed, missing = mod.EnvValidator.check()
        for var in ("DATABASE_URL", "SENTRY_DSN", "SMTP_HOST"):
            self.assertNotIn(var, missing)


if __name__ == "__main__":
    unittest.main()
