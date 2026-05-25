"""Tests for orchestra/api/server.py — FastAPI route handlers.

Covers: auth endpoints, billing endpoints (happy + 4xx), memory endpoints.
Uses FastAPI's synchronous TestClient so no pytest-asyncio is needed here.
Billing is exercised in two modes:
  1. billing=None (stripe initialisation raises, so routes return 503/stubs)
  2. billing mocked via patch (happy-path and error-path assertions)
"""

from __future__ import annotations

import importlib
import time
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(mock_billing: Any = None):
    """Create the FastAPI app. If mock_billing given, patch StripeBilling."""
    # Re-import so module-level state (_USERS, _MEMORIES) is fresh each call.
    import orchestra.api.server as srv
    srv._USERS.clear()
    if hasattr(srv, "_MEMORIES"):
        srv._MEMORIES.clear()

    from orchestra.api.server import APIConfig, create_production_app

    cfg = APIConfig(jwt_secret="pytest-secret-key-00000000000000", enable_security=False, enable_docs=False)

    if mock_billing is not None:
        with patch.object(srv, "StripeBilling", return_value=mock_billing), \
             patch.object(srv, "_BILLING_AVAILABLE", True):
            app = create_production_app(cfg)
    else:
        # Let billing initialise normally — it will be None or a real stub
        app = create_production_app(cfg)

    return app


def _get_test_client(app):
    from fastapi.testclient import TestClient
    return TestClient(app, raise_server_exceptions=False)


def _register_and_login(client) -> tuple[str, str]:
    """Register a fresh user and return (user_id, bearer_token)."""
    email = f"test_{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/v1/auth/register", json={
        "email": email, "name": "Test User", "password": "secret123"
    })
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    return data["user_id"], data["access_token"]


# ---------------------------------------------------------------------------
# Auth — register
# ---------------------------------------------------------------------------

class TestAuthRegister:
    def setup_method(self):
        self.app = _make_app()
        self.client = _get_test_client(self.app)

    def test_register_success(self):
        r = self.client.post("/v1/auth/register", json={
            "email": "new@example.com", "name": "Alice", "password": "pw"
        })
        assert r.status_code == 200
        body = r.json()
        assert body["error"] is None
        d = body["data"]
        assert "user_id" in d
        assert "access_token" in d
        assert "refresh_token" in d
        assert d["token_type"] == "Bearer"

    def test_register_duplicate_email_returns_400(self):
        payload = {"email": "dup@example.com", "name": "Bob", "password": "pw"}
        r1 = self.client.post("/v1/auth/register", json=payload)
        assert r1.status_code == 200
        r2 = self.client.post("/v1/auth/register", json=payload)
        assert r2.status_code == 400
        assert "already registered" in r2.json()["error"].lower()

    def test_register_missing_fields_returns_422(self):
        r = self.client.post("/v1/auth/register", json={"email": "x@x.com"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Auth — login
# ---------------------------------------------------------------------------

class TestAuthLogin:
    def setup_method(self):
        self.app = _make_app()
        self.client = _get_test_client(self.app)
        self.client.post("/v1/auth/register", json={
            "email": "login@example.com", "name": "Login User", "password": "correct"
        })

    def test_login_success(self):
        r = self.client.post("/v1/auth/login", json={
            "email": "login@example.com", "password": "correct"
        })
        assert r.status_code == 200
        d = r.json()["data"]
        assert "access_token" in d
        assert "refresh_token" in d

    def test_login_wrong_password_returns_401(self):
        r = self.client.post("/v1/auth/login", json={
            "email": "login@example.com", "password": "wrong"
        })
        assert r.status_code == 401
        assert r.json()["error"] is not None

    def test_login_unknown_email_returns_401(self):
        r = self.client.post("/v1/auth/login", json={
            "email": "ghost@example.com", "password": "any"
        })
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Auth — refresh
# ---------------------------------------------------------------------------

class TestAuthRefresh:
    def setup_method(self):
        self.app = _make_app()
        self.client = _get_test_client(self.app)
        r = self.client.post("/v1/auth/register", json={
            "email": "ref@example.com", "name": "Ref", "password": "pw"
        })
        self.refresh_token = r.json()["data"]["refresh_token"]

    def test_refresh_success(self):
        r = self.client.post("/v1/auth/refresh", json={"refresh_token": self.refresh_token})
        assert r.status_code == 200
        assert "access_token" in r.json()["data"]

    def test_refresh_with_access_token_returns_401(self):
        r_reg = self.client.post("/v1/auth/register", json={
            "email": "ref2@example.com", "name": "R2", "password": "pw"
        })
        access = r_reg.json()["data"]["access_token"]
        r = self.client.post("/v1/auth/refresh", json={"refresh_token": access})
        # Using an access token as refresh must be rejected
        assert r.status_code == 401

    def test_refresh_garbage_token_returns_401(self):
        r = self.client.post("/v1/auth/refresh", json={"refresh_token": "bad.token.here"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Auth — get_me
# ---------------------------------------------------------------------------

class TestGetMe:
    def setup_method(self):
        self.app = _make_app()
        self.client = _get_test_client(self.app)
        _, self.token = _register_and_login(self.client)

    def test_get_me_success(self):
        r = self.client.get("/v1/auth/me", headers={"Authorization": f"Bearer {self.token}"})
        assert r.status_code == 200
        d = r.json()["data"]
        assert "id" in d
        assert "password_hash" not in d  # must not leak password hash

    def test_get_me_no_token_returns_401(self):
        r = self.client.get("/v1/auth/me")
        assert r.status_code == 401

    def test_get_me_invalid_token_returns_401(self):
        r = self.client.get("/v1/auth/me", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Billing endpoints — billing=None (StripeBilling init raises)
# ---------------------------------------------------------------------------

class TestBillingNoBillingSystem:
    """When billing is unavailable the endpoints degrade gracefully."""

    def setup_method(self):
        import orchestra.api.server as srv
        # Force billing to be unavailable regardless of stripe install
        self.app = _make_app()
        # Patch the internal billing to None by creating app with failing init
        with patch("orchestra.api.server._BILLING_AVAILABLE", False):
            from orchestra.api.server import APIConfig, create_production_app
            srv._USERS.clear()
            cfg = APIConfig(jwt_secret="pytest-secret-key-00000000000000", enable_security=False)
            self.app = create_production_app(cfg)
        self.client = _get_test_client(self.app)
        _, self.token = _register_and_login(self.client)

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_checkout_returns_503_when_no_billing(self):
        r = self.client.post("/v1/billing/checkout", json={
            "tier": "pro", "success_url": "https://x.com/ok", "cancel_url": "https://x.com/cancel"
        }, headers=self._auth())
        assert r.status_code == 503
        assert r.json()["error"] is not None

    def test_portal_returns_503_when_no_billing(self):
        r = self.client.post("/v1/billing/portal", json={
            "return_url": "https://x.com/return"
        }, headers=self._auth())
        assert r.status_code == 503

    def test_subscription_returns_free_tier_stub(self):
        r = self.client.get("/v1/billing/subscription", headers=self._auth())
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["tier"] == "free"

    def test_usage_returns_allowed_true(self):
        r = self.client.get("/v1/billing/usage", headers=self._auth())
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["allowed"] is True

    def test_invoices_returns_empty_list(self):
        r = self.client.get("/v1/billing/invoices", headers=self._auth())
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_billing_requires_auth(self):
        for method, path, body in [
            ("POST", "/v1/billing/checkout", {"tier": "pro", "success_url": "x", "cancel_url": "y"}),
            ("POST", "/v1/billing/portal", {"return_url": "x"}),
            ("GET",  "/v1/billing/subscription", None),
            ("GET",  "/v1/billing/usage", None),
            ("GET",  "/v1/billing/invoices", None),
        ]:
            if method == "POST":
                r = self.client.post(path, json=body)
            else:
                r = self.client.get(path)
            assert r.status_code == 401, f"{method} {path} expected 401 got {r.status_code}"


# ---------------------------------------------------------------------------
# Billing endpoints — with mock billing
# ---------------------------------------------------------------------------

class TestBillingWithMockBilling:
    """Happy-path and error-path tests with a mocked StripeBilling."""

    def _make_mock_billing(self):
        from dataclasses import dataclass
        from datetime import datetime, timezone

        @dataclass
        class FakeSub:
            id: str = "sub_test"
            tier: str = "pro"
            status: str = "active"
            stripe_subscription_id: str = "stripe_sub_1"
            current_period_start: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
            current_period_end: datetime = datetime(2026, 2, 1, tzinfo=timezone.utc)
            cancel_at_period_end: bool = False
            created_at: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)

        @dataclass
        class FakeInvoice:
            id: str = "inv_1"
            stripe_invoice_id: str = "stripe_inv_1"
            amount: float = 20.0
            currency: str = "usd"
            status: str = "paid"
            period_start: datetime = datetime(2026, 1, 1, tzinfo=timezone.utc)
            period_end: datetime = datetime(2026, 2, 1, tzinfo=timezone.utc)
            line_items: list = None
            paid_at: datetime = datetime(2026, 1, 15, tzinfo=timezone.utc)
            pdf_url: str = "https://stripe.com/invoice.pdf"
            def __post_init__(self):
                if self.line_items is None:
                    self.line_items = []

        m = MagicMock()
        m.check_limits = AsyncMock(return_value={"allowed": True, "reason": "", "usage": {}, "limits": {}})
        m.get_subscription = AsyncMock(return_value=FakeSub())
        m.get_invoices = AsyncMock(return_value=[FakeInvoice()])
        m.record_usage = AsyncMock()
        m.create_customer = AsyncMock(return_value={"id": "cus_test123"})
        m.create_checkout_session = AsyncMock(return_value={
            "url": "https://checkout.stripe.com/pay/cs_test",
            "id": "cs_test",
        })
        m.create_portal_session = AsyncMock(return_value={
            "url": "https://billing.stripe.com/session/portal_test"
        })
        m.create_subscription = AsyncMock()
        m.handle_webhook = AsyncMock(return_value={"status": "ok", "event": "invoice.paid"})
        return m

    def setup_method(self):
        import orchestra.api.server as srv
        srv._USERS.clear()
        if hasattr(srv, "_MEMORIES"):
            srv._MEMORIES.clear()

        self.mock_billing = self._make_mock_billing()
        self.app = _make_app(mock_billing=self.mock_billing)
        self.client = _get_test_client(self.app)
        uid, tok = _register_and_login(self.client)
        self.user_id = uid
        self.token = tok

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_subscription_returns_details(self):
        r = self.client.get("/v1/billing/subscription", headers=self._auth())
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["tier"] == "pro"
        assert d["status"] == "active"

    def test_usage_returns_allowed(self):
        r = self.client.get("/v1/billing/usage", headers=self._auth())
        assert r.status_code == 200
        assert r.json()["data"]["allowed"] is True

    def test_invoices_returns_list(self):
        r = self.client.get("/v1/billing/invoices", headers=self._auth())
        assert r.status_code == 200
        invoices = r.json()["data"]
        assert isinstance(invoices, list)
        assert len(invoices) == 1
        assert invoices[0]["status"] == "paid"

    def test_checkout_happy_path(self):
        # Give the user a stripe_customer_id so checkout skips customer creation
        import orchestra.api.server as srv
        srv._USERS[self.user_id]["stripe_customer_id"] = "cus_existing"

        r = self.client.post("/v1/billing/checkout", json={
            "tier": "pro",
            "success_url": "https://app.example.com/success",
            "cancel_url": "https://app.example.com/cancel",
        }, headers=self._auth())
        assert r.status_code == 200
        d = r.json()["data"]
        assert "checkout_url" in d
        assert "session_id" in d

    def test_checkout_creates_customer_when_missing(self):
        # User has no stripe_customer_id — checkout should create one
        r = self.client.post("/v1/billing/checkout", json={
            "tier": "pro",
            "success_url": "https://x.com/ok",
            "cancel_url": "https://x.com/cancel",
        }, headers=self._auth())
        assert r.status_code == 200
        self.mock_billing.create_customer.assert_called_once()

    def test_portal_happy_path(self):
        import orchestra.api.server as srv
        srv._USERS[self.user_id]["stripe_customer_id"] = "cus_existing"

        r = self.client.post("/v1/billing/portal", json={
            "return_url": "https://app.example.com/settings"
        }, headers=self._auth())
        assert r.status_code == 200
        assert "portal_url" in r.json()["data"]

    def test_portal_returns_400_when_no_customer(self):
        # Registration auto-creates a Stripe customer when billing is enabled,
        # so explicitly clear it to simulate a user without a linked customer.
        import orchestra.api.server as srv
        srv._USERS[self.user_id]["stripe_customer_id"] = None

        r = self.client.post("/v1/billing/portal", json={
            "return_url": "https://x.com"
        }, headers=self._auth())
        assert r.status_code == 400
        assert r.json()["error"] is not None

    def test_checkout_propagates_billing_error_as_500(self):
        import orchestra.api.server as srv
        srv._USERS[self.user_id]["stripe_customer_id"] = "cus_existing"
        self.mock_billing.create_checkout_session = AsyncMock(
            side_effect=RuntimeError("Stripe timeout")
        )
        r = self.client.post("/v1/billing/checkout", json={
            "tier": "pro",
            "success_url": "https://x.com/ok",
            "cancel_url": "https://x.com/cancel",
        }, headers=self._auth())
        assert r.status_code == 500
        assert "Stripe timeout" in r.json()["error"]

    def test_webhook_happy_path(self):
        r = self.client.post("/v1/billing/webhook", content=b'{"type":"invoice.paid"}',
                             headers={"stripe-signature": "t=123,v1=abc"})
        assert r.status_code == 200
        assert r.json()["data"]["status"] == "ok"

    def test_webhook_billing_error_returns_400(self):
        self.mock_billing.handle_webhook = AsyncMock(
            side_effect=ValueError("invalid signature")
        )
        r = self.client.post("/v1/billing/webhook", content=b'{}',
                             headers={"stripe-signature": "bad"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Memory endpoints
# ---------------------------------------------------------------------------

class TestMemoryEndpoints:
    def setup_method(self):
        self.app = _make_app()
        self.client = _get_test_client(self.app)
        _, self.token = _register_and_login(self.client)

    def _auth(self):
        return {"Authorization": f"Bearer {self.token}"}

    def test_store_then_list(self):
        r = self.client.post("/v1/memory/store", json={
            "content": "Remember the Alamo",
            "metadata": {"source": "test"},
            "tags": ["history"],
        }, headers=self._auth())
        assert r.status_code == 200
        assert "id" in r.json()["data"]

        r2 = self.client.get("/v1/memory/list", headers=self._auth())
        assert r2.status_code == 200
        memories = r2.json()["data"]
        assert any("Alamo" in m["content"] for m in memories)

    def test_search_finds_stored_memory(self):
        self.client.post("/v1/memory/store", json={
            "content": "Unique token XYZ99", "metadata": {}, "tags": []
        }, headers=self._auth())

        r = self.client.post("/v1/memory/search", json={
            "query": "XYZ99", "limit": 5
        }, headers=self._auth())
        assert r.status_code == 200
        results = r.json()["data"]
        assert any("XYZ99" in m["content"] for m in results)

    def test_search_returns_empty_when_no_match(self):
        r = self.client.post("/v1/memory/search", json={
            "query": "absolutely_not_stored_zzzzzz", "limit": 5
        }, headers=self._auth())
        assert r.status_code == 200
        assert r.json()["data"] == []

    def test_memory_endpoints_require_auth(self):
        for method, path, body in [
            ("POST", "/v1/memory/store", {"content": "x", "metadata": {}, "tags": []}),
            ("POST", "/v1/memory/search", {"query": "x", "limit": 1}),
            ("GET",  "/v1/memory/list", None),
        ]:
            if method == "POST":
                r = self.client.post(path, json=body)
            else:
                r = self.client.get(path)
            assert r.status_code == 401, f"{path} should require auth"


# ---------------------------------------------------------------------------
# Models endpoint
# ---------------------------------------------------------------------------

class TestModelsEndpoint:
    def setup_method(self):
        self.app = _make_app()
        self.client = _get_test_client(self.app)
        _, self.token = _register_and_login(self.client)

    def test_list_models_returns_non_empty(self):
        r = self.client.get("/v1/models",
                            headers={"Authorization": f"Bearer {self.token}"})
        assert r.status_code == 200
        models = r.json()["data"]
        assert len(models) > 0
        for m in models:
            assert "id" in m
            assert "provider" in m

    def test_list_models_requires_auth(self):
        r = self.client.get("/v1/models")
        assert r.status_code == 401
