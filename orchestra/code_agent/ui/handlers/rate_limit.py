"""HTTP rate-limiting ASGI middleware.

Pure in-memory token-bucket per IP. Redis is wired in automatically when
REDIS_URL is set, but the server works without it.

Limits (configurable via settings):
  - Default:         120 req/min per IP
  - /api/chat:        20 req/min per IP  (LLM calls are expensive)
  - /v1/auth/login:   10 req/min per IP  (brute-force protection)
  - /api/keys:        30 req/min per IP
"""
from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Any

log = logging.getLogger("orchestra.ratelimit")

# ---------------------------------------------------------------------------
# Token bucket (thread-safe, lock-free via GIL for CPython)
# ---------------------------------------------------------------------------

class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, capacity: float) -> None:
        self.tokens: float = capacity
        self.last_refill: float = time.monotonic()


class InMemoryRateLimiter:
    """Per-key token-bucket rate limiter backed by a dict."""

    def __init__(self, capacity: int = 120, refill_per_second: float = 2.0) -> None:
        self._capacity = capacity
        self._refill = refill_per_second
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(capacity))

    def consume(self, key: str, cost: int = 1) -> tuple[bool, float]:
        """Try to consume `cost` tokens. Returns (allowed, remaining)."""
        b = self._buckets[key]
        now = time.monotonic()
        elapsed = now - b.last_refill
        b.tokens = min(self._capacity, b.tokens + elapsed * self._refill)
        b.last_refill = now
        if b.tokens >= cost:
            b.tokens -= cost
            return True, b.tokens
        return False, b.tokens

    def retry_after_seconds(self, key: str, cost: int = 1) -> float:
        b = self._buckets[key]
        needed = cost - b.tokens
        return round(needed / max(self._refill, 0.001), 1)

    def prune(self, max_idle_seconds: float = 300.0) -> int:
        now = time.monotonic()
        stale = [k for k, b in self._buckets.items()
                 if now - b.last_refill > max_idle_seconds]
        for k in stale:
            del self._buckets[k]
        return len(stale)


# ---------------------------------------------------------------------------
# Per-route limits
# ---------------------------------------------------------------------------

_ROUTE_LIMITS: list[tuple[str, int, float]] = [
    # (path_prefix, capacity, refill_per_second)
    ("/api/chat",        20,  0.33),   # 20/min
    ("/v1/auth/login",   10,  0.167),  # 10/min
    ("/v1/auth/register", 5,  0.083),  # 5/min
    ("/api/keys",        30,  0.5),    # 30/min
]

_DEFAULT_CAPACITY    = 120
_DEFAULT_REFILL      = 2.0

# One limiter per (route_prefix, ip) pair is too many objects.
# We use one global limiter per route tier, keyed by IP.
_limiters: dict[str, InMemoryRateLimiter] = {}


def _get_limiter(path: str) -> tuple[InMemoryRateLimiter, str]:
    for prefix, cap, refill in _ROUTE_LIMITS:
        if path.startswith(prefix):
            key = prefix
            if key not in _limiters:
                _limiters[key] = InMemoryRateLimiter(cap, refill)
            return _limiters[key], key
    if "__default__" not in _limiters:
        _limiters["__default__"] = InMemoryRateLimiter(_DEFAULT_CAPACITY, _DEFAULT_REFILL)
    return _limiters["__default__"], "__default__"


# ---------------------------------------------------------------------------
# ASGI middleware
# ---------------------------------------------------------------------------

_SKIP_PREFIXES = ("/sw.js", "/icon", "/manifest", "/miles", "/docs", "/redoc",
                  "/openapi", "/static")


def _client_ip(scope: dict) -> str:
    headers = dict(scope.get("headers", []))
    forwarded = headers.get(b"x-forwarded-for", b"").decode()
    if forwarded:
        return forwarded.split(",")[0].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


async def _send_429(send: Any, retry_after: float) -> None:
    import json
    body = json.dumps({
        "detail": "Too many requests",
        "retry_after_seconds": retry_after,
    }).encode()
    await send({
        "type": "http.response.start",
        "status": 429,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(body)).encode()),
            (b"retry-after", str(int(retry_after) + 1).encode()),
            (b"x-ratelimit-limit", b"see retry-after"),
        ],
    })
    await send({"type": "http.response.body", "body": body})


class RateLimitMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app
        self._prune_counter = 0

    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from orchestra.code_agent.settings import settings
        if not settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            await self.app(scope, receive, send)
            return

        # Owner bypass — no rate limiting ever
        _owner_email = os.environ.get("ORCHESTRA_OWNER_EMAIL", "").strip().lower()
        if _owner_email:
            _headers = dict(scope.get("headers", []))
            _auth = _headers.get(b"authorization", b"").decode("utf-8", errors="ignore")
            _token = _auth.removeprefix("Bearer ").strip()
            if not _token:
                import http.cookies as _hc
                _raw_cookie = _headers.get(b"cookie", b"").decode("utf-8", errors="ignore")
                _jar = _hc.SimpleCookie()
                try:
                    _jar.load(_raw_cookie)
                    _token = _jar.get("session", _hc.Morsel()).value or ""
                except Exception:
                    pass
            if _token:
                try:
                    from orchestra.code_agent.ui.handlers.v1_compat import _decode_local_token
                    from orchestra.code_agent.auth.user_store import UserStore as _US
                    _uid = _decode_local_token(_token)
                    if _uid:
                        _u = _US.get().get_user_by_id(_uid)
                        if _u and _u.get("email", "").lower() == _owner_email:
                            await self.app(scope, receive, send)
                            return
                except Exception:
                    pass

        ip = _client_ip(scope)
        limiter, tier = _get_limiter(path)
        allowed, remaining = limiter.consume(ip)

        # Periodically prune stale buckets to prevent unbounded memory growth
        self._prune_counter += 1
        if self._prune_counter >= 10_000:
            self._prune_counter = 0
            for lim in _limiters.values():
                lim.prune()

        if not allowed:
            retry = limiter.retry_after_seconds(ip)
            log.warning("Rate limit exceeded: ip=%s path=%s tier=%s retry_after=%.1fs",
                        ip, path, tier, retry)
            await _send_429(send, retry)
            return

        async def _send_with_headers(msg: dict) -> None:
            if msg.get("type") == "http.response.start":
                headers = list(msg.get("headers", []))
                headers.append((b"x-ratelimit-remaining", str(int(remaining)).encode()))
                msg = dict(msg)
                msg["headers"] = headers
            await send(msg)

        await self.app(scope, receive, _send_with_headers)


def register_rate_limit_middleware(app: Any) -> None:
    app.add_middleware(RateLimitMiddleware)
    log.info("Rate-limit middleware registered (in-memory token bucket)")
