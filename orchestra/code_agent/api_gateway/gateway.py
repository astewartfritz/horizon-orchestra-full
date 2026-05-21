"""OrchestraGateway — production API gateway that stacks all middleware."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from orchestra.code_agent.api_gateway.middleware.auth import AuthConfig, AuthMiddleware, AuthResult
from orchestra.code_agent.api_gateway.middleware.rate_limiter import RateLimiter, RateLimitRule
from orchestra.code_agent.api_gateway.middleware.logging import LoggingMiddleware
from orchestra.code_agent.api_gateway.middleware.validation import ValidationMiddleware


class OrchestraGateway:
    """Production API Gateway with stacked middleware pipeline.

    Middleware order (outermost → innermost):
      1. Logging / Tracing
      2. Rate Limiting
      3. Authentication (JWT + API key)
      4. Validation (content-type, size)
      5. CORS headers
      6. Error handling
    """

    def __init__(self, jwt_secret: str = "", max_body_size: int = 10 * 1024 * 1024):
        self.logger = logging.getLogger("orchestra.gateway")
        self.auth_config = AuthConfig(jwt_secret=jwt_secret or uuid.uuid4().hex)

        self.rate_limiter = RateLimiter()
        self.auth = AuthMiddleware(jwt_config=self.auth_config)
        self.logging = LoggingMiddleware()
        self.validation = ValidationMiddleware(max_body_size=max_body_size)

        self._routes: dict[str, dict[str, Any]] = {}
        self._route_order: list[str] = []
        self._rate_limit_whitelist: set[str] = set()

    def add_route(self, path: str, method: str, handler: Callable,
                  rate_limit: int | None = None, auth_required: bool = True) -> None:
        """Register a route with its auth and rate-limit policy."""
        key = f"{method.upper()}:{path}"
        self._routes[key] = {
            "path": path,
            "method": method.upper(),
            "handler": handler,
            "rate_limit": rate_limit,
            "auth_required": auth_required,
        }
        if key not in self._route_order:
            self._route_order.append(key)

    def add_rate_limit_whitelist(self, path: str) -> None:
        self._rate_limit_whitelist.add(path)

    async def handle(self, request: Request, call_next: Callable) -> JSONResponse:
        """Main middleware handler. Called by FastAPI for every request."""
        start = time.time()
        trace_id = uuid.uuid4().hex[:12]
        request.state.trace_id = trace_id

        # ── 1. Path-based bypass for public endpoints ──────────
        path = request.url.path
        method = request.method
        route_key = f"{method}:{path}"

        # ── 2. Rate limiting (skip whitelisted paths) ──────────
        if path not in self._rate_limit_whitelist:
            ip = request.client.host if request.client else "unknown"
            user = getattr(request.state, "user_id", "")
            allowed, headers = self.rate_limiter.check(ip=ip, user=user, endpoint=path)
            if not allowed:
                self.logger.warning("Rate limit exceeded: %s %s from %s", method, path, ip)
                return JSONResponse(
                    status_code=429,
                    content={"error": "Too many requests", "retry_after": headers.get("Retry-After", "1")},
                    headers=headers,
                )

        # ── 3. Authentication ──────────────────────────────────
        route = self._routes.get(route_key)
        auth_required = route["auth_required"] if route else True

        if auth_required:
            auth_result = await self.auth.authenticate(request)
            if not auth_result.authenticated:
                self.logger.warning("Auth failed: %s %s — %s", method, path, auth_result.error)
                return JSONResponse(
                    status_code=401,
                    content={"error": auth_result.error, "trace_id": trace_id},
                )
            request.state.user_id = auth_result.user_id
            request.state.role = auth_result.role
            request.state.permissions = auth_result.permissions
            request.state.token_type = auth_result.token_type
        else:
            request.state.user_id = "anonymous"
            request.state.role = "readonly"

        # ── 4. Content validation ──────────────────────────────
        if method in ("POST", "PUT", "PATCH"):
            ct = request.headers.get("content-type", "")
            if not ct and path not in ("/webhook",):
                return JSONResponse(
                    status_code=415,
                    content={"error": "Content-Type header required", "trace_id": trace_id},
                )
            cl = request.headers.get("content-length", "0")
            try:
                if int(cl) > self.validation.max_body_size:
                    return JSONResponse(
                        status_code=413,
                        content={"error": f"Body too large (max {self.validation.max_body_size // 1024 // 1024}MB)", "trace_id": trace_id},
                    )
            except ValueError:
                pass

        # ── 5. Forward to handler ──────────────────────────────
        try:
            response = await call_next(request)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"error": exc.detail, "trace_id": trace_id},
            )
        except Exception as exc:
            self.logger.exception("Unhandled error: %s %s", method, path)
            return JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "trace_id": trace_id},
            )

        # ── 6. Add trace headers to response ───────────────────
        elapsed = int((time.time() - start) * 1000)
        response.headers["x-trace-id"] = trace_id
        response.headers["x-response-time-ms"] = str(elapsed)

        return response

    def register_into(self, app: FastAPI) -> None:
        """Register this gateway as middleware on a FastAPI app."""
        app.add_middleware(CORSMiddlewareAdapter)
        app.middleware("http")(self.handle)

    def get_stats(self) -> dict[str, Any]:
        return {
            "routes": len(self._routes),
            "rate_limit_rules": len(self.rate_limiter._rules),
            "api_keys": len(self.auth.api_keys._keys),
        }


class CORSMiddlewareAdapter:
    """CORS middleware — allows API access from any origin."""
    # FastAPI handles this via CORSMiddleware; this is a marker.
    pass
