"""Tests for the production API Gateway — rate limiter, auth, middleware stack."""

from __future__ import annotations

import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from api_gateway.gateway import OrchestraGateway
from api_gateway.middleware.auth import AuthConfig, AuthMiddleware, JWTAuthMiddleware, APIKeyAuth
from api_gateway.middleware.rate_limiter import RateLimiter, RateLimitRule, TokenBucket


# ── Token Bucket ──────────────────────────────────────────

class TestTokenBucket:
    def test_consume_returns_true_when_tokens_available(self):
        bucket = TokenBucket(capacity=10, refill_rate=1)
        assert bucket.consume(1) is True
        assert bucket.consume(5) is True
        assert bucket.consume(10) is False

    def test_refills_over_time(self):
        bucket = TokenBucket(capacity=10, refill_rate=10)
        bucket.consume(10)
        bucket.last_refill = time.time() - 2
        assert bucket.consume(10) is True

    def test_capacity_not_exceeded(self):
        bucket = TokenBucket(capacity=5, refill_rate=100)
        # Manually set last_refill far back and tokens to huge value
        # consume will cap at capacity
        bucket.last_refill = time.time() - 10
        bucket.tokens = 100.0
        # consume triggers refill calculation which caps at capacity
        bucket.consume(0)
        assert bucket.tokens <= 5


# ── Rate Limiter ──────────────────────────────────────────

class TestRateLimiter:
    def test_allows_within_limit(self):
        limiter = RateLimiter()
        allowed, headers = limiter.check(ip="1.2.3.4")
        assert allowed is True
        assert "X-RateLimit-Limit" in headers

    def test_global_rate_limit(self):
        limiter = RateLimiter()
        limiter._rules = [RateLimitRule(requests=3, window_seconds=60, scope="ip")]
        for _ in range(3):
            allowed, _ = limiter.check(ip="5.6.7.8")
            assert allowed is True
        allowed, headers = limiter.check(ip="5.6.7.8")
        assert allowed is False
        assert "Retry-After" in headers

    def test_different_ips_not_affected(self):
        limiter = RateLimiter()
        limiter._rules = [RateLimitRule(requests=1, window_seconds=60, scope="ip")]
        allowed, _ = limiter.check(ip="10.0.0.1")
        assert allowed is True
        allowed, _ = limiter.check(ip="10.0.0.1")
        assert allowed is False
        allowed, _ = limiter.check(ip="10.0.0.2")
        assert allowed is True

    def test_add_rule(self):
        limiter = RateLimiter()
        limiter.add_rule(RateLimitRule(requests=999, window_seconds=1, scope="global"))
        assert len(limiter._rules) == 5

    def test_cleanup_removes_stale_buckets(self):
        limiter = RateLimiter()
        limiter.check(ip="old.ip")
        assert len(limiter._buckets) > 0
        for b in limiter._buckets.values():
            b.last_refill = 0
        limiter.cleanup(max_age=1)
        assert len(limiter._buckets) == 0


# ── JWT Auth ──────────────────────────────────────────────

class TestJWTAuthMiddleware:
    def test_create_and_verify_token(self):
        jwt = JWTAuthMiddleware(AuthConfig(jwt_secret="test-secret"))
        token = jwt.create_token("user123", role="admin", permissions=["read", "write"])
        result = jwt.verify_token(token)
        assert result.authenticated is True
        assert result.user_id == "user123"
        assert result.role == "admin"
        assert "read" in result.permissions

    def test_rejects_expired_token(self):
        jwt = JWTAuthMiddleware(AuthConfig(jwt_secret="test-secret"))
        import jwt as _jwt
        expired = _jwt.encode(
            {"sub": "user", "exp": 0, "iat": 0},
            "test-secret", algorithm="HS256",
        )
        result = jwt.verify_token(expired)
        assert result.authenticated is False
        assert "expired" in result.error.lower()

    def test_rejects_invalid_token(self):
        jwt = JWTAuthMiddleware(AuthConfig(jwt_secret="test-secret"))
        result = jwt.verify_token("not-a-valid-token")
        assert result.authenticated is False

    def test_different_secret_fails(self):
        jwt = JWTAuthMiddleware(AuthConfig(jwt_secret="secret-a"))
        token = jwt.create_token("user")
        jwt2 = JWTAuthMiddleware(AuthConfig(jwt_secret="secret-b"))
        result = jwt2.verify_token(token)
        assert result.authenticated is False


# ── API Key Auth ──────────────────────────────────────────

class TestAPIKeyAuth:
    def test_create_and_verify_key(self):
        auth = APIKeyAuth()
        key = auth.create_key("user456", role="readonly")
        assert key.startswith("orch_")
        result = auth.verify(key)
        assert result.authenticated is True
        assert result.user_id == "user456"
        assert result.role == "readonly"

    def test_rejects_invalid_key(self):
        auth = APIKeyAuth()
        result = auth.verify("not-a-real-key")
        assert result.authenticated is False

    def test_revoke_key(self):
        auth = APIKeyAuth()
        key = auth.create_key("user", "admin")
        assert auth.verify(key).authenticated is True
        assert auth.revoke(key) is True
        assert auth.verify(key).authenticated is False

    def test_revoke_nonexistent(self):
        auth = APIKeyAuth()
        assert auth.revoke("nonexistent") is False


# ── Auth Middleware ───────────────────────────────────────

class TestAuthMiddleware:
    def make_request(self, path: str, headers: dict | None = None) -> Request:
        raw_headers = [(b"host", b"localhost")]
        if headers:
            for k, v in headers.items():
                raw_headers.append((k.lower().encode(), v.encode()))
        scope = {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": raw_headers,
            "client": ("127.0.0.1", 50000),
        }
        return Request(scope)

    @pytest.mark.asyncio
    async def test_public_paths_skipped(self):
        auth = AuthMiddleware()
        req = self.make_request("/health")
        result = await auth.authenticate(req)
        assert result.authenticated is True
        assert result.user_id == "anonymous"

    @pytest.mark.asyncio
    async def test_no_auth_header_returns_unauthenticated(self):
        auth = AuthMiddleware()
        req = self.make_request("/api/chat")
        result = await auth.authenticate(req)
        assert result.authenticated is False

    @pytest.mark.asyncio
    async def test_valid_jwt_token(self):
        auth = AuthMiddleware(AuthConfig(jwt_secret="test"))
        token = auth.jwt.create_token("alice", "admin")
        req = self.make_request("/api/chat", {"Authorization": f"Bearer {token}"})
        result = await auth.authenticate(req)
        assert result.authenticated is True
        assert result.user_id == "alice"

    @pytest.mark.asyncio
    async def test_valid_api_key(self):
        auth = AuthMiddleware()
        key = auth.api_keys.create_key("bob")
        req = self.make_request("/api/chat", {"X-API-Key": key})
        result = await auth.authenticate(req)
        assert result.authenticated is True
        assert result.user_id == "bob"


# ── Orchestra Gateway ─────────────────────────────────────

class TestOrchestraGateway:
    @pytest.mark.asyncio
    async def test_health_passthrough(self):
        gateway = OrchestraGateway(jwt_secret="test")
        request = MagicMock(spec=Request)
        request.url.path = "/health"
        request.method = "GET"
        request.client.host = "127.0.0.1"
        request.state = MagicMock()

        async def call_next(req):
            return JSONResponse({"status": "ok"})

        response = await gateway.handle(request, call_next)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_rate_limit_exceeded(self):
        gateway = OrchestraGateway(jwt_secret="test")
        gateway.rate_limiter._rules = [RateLimitRule(requests=1, window_seconds=60, scope="ip")]
        allowed, headers = gateway.rate_limiter.check(ip="10.0.0.1")
        assert allowed is True
        allowed, headers = gateway.rate_limiter.check(ip="10.0.0.1")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_add_route(self):
        gateway = OrchestraGateway(jwt_secret="test")

        async def handler(request):
            return {"handled": True}

        gateway.add_route("/test", "GET", handler, rate_limit=100, auth_required=False)
        assert "GET:/test" in gateway._routes
        assert gateway._routes["GET:/test"]["auth_required"] is False

    def test_get_stats(self):
        gateway = OrchestraGateway(jwt_secret="test")
        gateway.add_route("/a", "GET", lambda r: None)
        stats = gateway.get_stats()
        assert stats["routes"] >= 1
        assert stats["rate_limit_rules"] >= 1


# ── FastAPI Integration ───────────────────────────────────

@pytest.fixture
def test_app():
    from api_gateway.server import create_app
    app = create_app()
    return app


class TestFastAPIIntegration:
    @pytest.mark.asyncio
    async def test_health_endpoint(self, test_app):
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_chat_returns_401_without_auth(self, test_app):
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/chat", json={"content": "hello"})
            assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_auth_token_endpoint(self, test_app):
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/token", json={"user_id": "alice", "role": "admin"})
            assert resp.status_code == 200
            data = resp.json()
            assert "access_token" in data
            assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_auth_token_missing_user_id(self, test_app):
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/token", json={"role": "admin"})
            assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_api_key_creation(self, test_app):
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/auth/api-key", json={"user_id": "bob"})
            assert resp.status_code == 200
            data = resp.json()
            assert data["api_key"].startswith("orch_")

    @pytest.mark.asyncio
    async def test_chat_with_jwt(self, test_app):
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            token_resp = await client.post("/auth/token", json={"user_id": "alice"})
            token = token_resp.json()["access_token"]
            resp = await client.post(
                "/api/chat",
                json={"content": "hello"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code in (200, 500)

    @pytest.mark.asyncio
    async def test_gateway_starts_with_cors(self, test_app):
        from httpx import AsyncClient, ASGITransport
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health", headers={"Origin": "http://example.com"})
            assert resp.status_code == 200
            assert "access-control-allow-origin" in resp.headers
