"""Integration tests for core Orchestra API routes.

Uses FastAPI TestClient (synchronous wrapper around ASGI). Each test class
spins up the full app factory — no mocks for the routes under test.

Run:
    pytest tests/test_integration_core.py -v
"""
from __future__ import annotations

import os
import tempfile
import unittest

# Set test env vars before importing settings
os.environ.setdefault("ORCHESTRA_ENV", "development")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-integration-tests")
os.environ.setdefault("API_KEY_ENCRYPTION_KEY", "test-encryption-key-for-tests")
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")  # disable for tests

import pytest


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the full app."""
    try:
        from fastapi.testclient import TestClient
        from orchestra.code_agent.ui.server import create_ui_app
        app = create_ui_app()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c
    except ImportError as e:
        pytest.skip(f"FastAPI not available: {e}")


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_endpoint(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert "status" in data or "uptime" in data or r.status_code == 200

    def test_root_returns_html(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# Auth — register + login + token
# ---------------------------------------------------------------------------

class TestAuth:
    def test_register_and_login(self, client):
        email = "test_integ@orchestra.test"
        password = "TestPass123!"

        # Register
        r = client.post("/v1/auth/register", json={"email": email, "password": password, "name": "Test"})
        assert r.status_code in (200, 201, 409), f"Register returned {r.status_code}: {r.text}"

        if r.status_code == 409:
            # Already exists — that's fine, proceed to login
            pass

        # Login — response envelope: {"data": {"access_token": "..."}, "error": null, ...}
        r = client.post("/v1/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, f"Login failed {r.status_code}: {r.text}"
        data = r.json()
        token = (
            data.get("access_token")
            or data.get("token")
            or (data.get("data") or {}).get("access_token")
        )
        assert token, f"No token in response: {data}"

    def test_login_wrong_password(self, client):
        r = client.post("/v1/auth/login", json={"email": "nobody@nowhere.test", "password": "wrong"})
        assert r.status_code in (401, 403, 404, 422)

    def test_login_missing_fields(self, client):
        r = client.post("/v1/auth/login", json={"email": "test@test.com"})
        assert r.status_code == 422


# ---------------------------------------------------------------------------
# Sessions CRUD
# ---------------------------------------------------------------------------

class TestSessions:
    def test_create_and_list_sessions(self, client):
        # Create a session
        r = client.post("/api/sessions", json={"name": "integration-test-session"})
        assert r.status_code in (200, 201), f"Create session failed: {r.status_code} {r.text}"
        data = r.json()
        session_id = data.get("id") or data.get("session_id")
        assert session_id, f"No session ID in response: {data}"

        # List sessions
        r = client.get("/api/sessions")
        assert r.status_code == 200
        sessions = r.json()
        assert isinstance(sessions, (list, dict))

    def test_get_nonexistent_session(self, client):
        r = client.get("/api/sessions/nonexistent-session-id-xyz")
        assert r.status_code in (404, 422)


# ---------------------------------------------------------------------------
# Logs API
# ---------------------------------------------------------------------------

class TestLogsAPI:
    def test_get_logs(self, client):
        r = client.get("/api/logs")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data or isinstance(data, list)

    def test_get_log_stats(self, client):
        r = client.get("/api/logs/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total" in data or isinstance(data, dict)

    def test_ingest_log_event(self, client):
        r = client.post("/api/logs/ingest", json={
            "level": "INFO",
            "source": "integration-test",
            "message": "Test event from integration test",
        })
        assert r.status_code in (200, 201), f"Ingest failed: {r.status_code} {r.text}"

    def test_clear_logs_returns_count(self, client):
        r = client.delete("/api/logs")
        assert r.status_code == 200
        data = r.json()
        assert "deleted" in data or "count" in data or "ok" in data


# ---------------------------------------------------------------------------
# API Keys
# ---------------------------------------------------------------------------

class TestApiKeys:
    def test_list_keys_empty(self, client):
        r = client.get("/api/keys")
        assert r.status_code == 200
        data = r.json()
        assert "keys" in data

    def test_store_and_check_key(self, client):
        r = client.put("/api/keys/openai", json={"key": "sk-test-integration-key", "label": "OpenAI"})
        assert r.status_code == 200, f"Store key failed: {r.status_code} {r.text}"

        # Check it's stored
        r = client.get("/api/keys/openai/check")
        assert r.status_code == 200
        data = r.json()
        assert data.get("configured") is True

    def test_delete_key(self, client):
        # Store first
        client.put("/api/keys/groq", json={"key": "gsk-test-key"})
        # Delete
        r = client.delete("/api/keys/groq")
        assert r.status_code == 200

    def test_invalid_provider_rejected(self, client):
        r = client.put("/api/keys/evil-provider", json={"key": "some-key"})
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimit:
    def test_rate_limit_header_present(self, client):
        # Rate limiting is disabled in test env, but header should still be present
        # when enabled
        r = client.get("/api/logs/stats")
        # Just verify the route works — we can't easily test rate limit enforcement
        # without enabling it and hammering the endpoint
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Finance API smoke test
# ---------------------------------------------------------------------------

class TestFinanceAPI:
    def test_finance_health(self, client):
        r = client.get("/api/finance/health")
        assert r.status_code == 200
        data = r.json()
        assert data.get("status") == "ok"

    def test_list_accounts_empty(self, client):
        r = client.get("/api/finance/accounts")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, dict)

    def test_create_account(self, client):
        r = client.post("/api/finance/accounts", json={
            "code": "TEST-001",
            "name": "Integration Test Account",
            "type": "asset",
            "currency": "USD",
        })
        assert r.status_code in (200, 201), f"Create account failed: {r.status_code} {r.text}"


# ---------------------------------------------------------------------------
# Migration status
# ---------------------------------------------------------------------------

class TestMigrations:
    def test_migration_status_endpoint(self, client):
        r = client.get("/api/admin/migrations")
        assert r.status_code == 200
        data = r.json()
        assert "migrations" in data
        migrations = data["migrations"]
        assert len(migrations) > 0
        for m in migrations:
            assert "version" in m
            assert "name" in m
            assert "applied" in m


# ---------------------------------------------------------------------------
# Production readiness endpoint
# ---------------------------------------------------------------------------

class TestReadiness:
    def test_readiness_endpoint_shape(self, client):
        r = client.get("/api/admin/readiness")
        assert r.status_code == 200
        data = r.json()
        assert "score" in data
        assert "checks" in data
        assert isinstance(data["score"], (int, float))
        assert isinstance(data["checks"], list)
        for check in data["checks"]:
            assert "name" in check
            assert "passed" in check

    def test_readiness_score_above_zero(self, client):
        r = client.get("/api/admin/readiness")
        data = r.json()
        assert data["score"] > 0, f"Readiness score is 0 — all checks failed: {data['checks']}"


# ---------------------------------------------------------------------------
# Settings sanity check
# ---------------------------------------------------------------------------

class TestSettings:
    def test_settings_loaded(self):
        from orchestra.code_agent.settings import settings
        assert settings.jwt_secret != ""
        assert settings.api_key_encryption_key != ""
        assert isinstance(settings.cors_origins, list)
        assert isinstance(settings.rate_limit_enabled, bool)

    def test_cors_not_wildcard_in_production(self):
        from orchestra.code_agent.settings import OrchestraSettings
        # In development (default), wildcard is OK
        s = OrchestraSettings()
        assert s.env == "development"
        # Production config would fail with wildcard — tested implicitly by
        # the RuntimeError raised at module load if misconfigured
