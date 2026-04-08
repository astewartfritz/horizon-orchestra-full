from __future__ import annotations

"""
Production API server for Horizon Orchestra.

Serves iOS, web, desktop, and browser extension clients.

Endpoints cover:
    /v1/auth/...       — authentication (register, login, refresh, me)
    /v1/run            — task execution
    /v1/stream         — WebSocket streaming
    /v1/query          — direct model query
    /v1/billing/...    — Stripe billing management
    /v1/memory/...     — memory store operations
    /v1/files/...      — workspace file management
    /v1/models         — model catalogue
    /v1/connectors/... — connector registry
    /v1/admin/...      — admin-only operations
    /v1/push/...       — push notification registration & delivery

All endpoints return:
    {"data": ..., "error": ..., "meta": {"request_id": ..., "duration_ms": ...}}

Import guard: if FastAPI is not installed, the module is still importable;
create_production_app() raises ImportError at call time.
"""

__all__ = [
    "ProductionAPI",
    "APIConfig",
    "create_production_app",
]

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guard — FastAPI / Uvicorn
# ---------------------------------------------------------------------------
try:
    import fastapi
    from fastapi import (
        Depends,
        FastAPI,
        File,
        Header,
        HTTPException,
        Request,
        UploadFile,
        WebSocket,
        WebSocketDisconnect,
        status,
    )
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import JSONResponse, StreamingResponse
    import uvicorn
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False
    # Provide stub types so the module still loads
    FastAPI = None          # type: ignore[assignment,misc]
    Request = None          # type: ignore[assignment,misc]

try:
    from pydantic import BaseModel, Field
    _PYDANTIC_AVAILABLE = True
except ImportError:
    _PYDANTIC_AVAILABLE = False
    BaseModel = object      # type: ignore[assignment,misc]

    def Field(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        return None

# ---------------------------------------------------------------------------
# Local imports (optional — guarded per-use)
# ---------------------------------------------------------------------------
try:
    from ..billing import StripeBilling, BillingConfig
    _BILLING_AVAILABLE = True
except ImportError:
    _BILLING_AVAILABLE = False

try:
    from ..security import SecurityHardening, SecurityConfig
    _SECURITY_AVAILABLE = True
except ImportError:
    _SECURITY_AVAILABLE = False


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass
class APIConfig:
    """Configuration for the production API server."""

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    enable_docs: bool = True
    stripe_webhook_path: str = "/v1/billing/webhook"
    ws_path: str = "/v1/stream"
    api_version: str = "v1"
    max_request_size_mb: int = 10
    enable_security: bool = True
    jwt_secret: str = field(
        default_factory=lambda: os.environ.get("JWT_SECRET", "change-me-in-production")
    )
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------

def _make_jwt(payload: dict[str, Any], secret: str, algorithm: str, expire_minutes: int) -> str:
    """Create a signed JWT. Falls back to a simple base64 token if PyJWT missing."""
    try:
        import jwt as pyjwt
        import datetime as dt
        payload = {
            **payload,
            "exp": dt.datetime.utcnow() + dt.timedelta(minutes=expire_minutes),
            "iat": dt.datetime.utcnow(),
            "jti": str(uuid.uuid4()),
        }
        return pyjwt.encode(payload, secret, algorithm=algorithm)
    except ImportError:
        import base64, json
        raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
        return f"basic.{raw}.nosig"


def _decode_jwt(token: str, secret: str, algorithm: str) -> dict[str, Any]:
    """Decode and verify a JWT. Raises ValueError on failure."""
    try:
        import jwt as pyjwt
        return pyjwt.decode(token, secret, algorithms=[algorithm])
    except ImportError:
        import base64, json
        parts = token.split(".")
        if len(parts) >= 2:
            try:
                pad = parts[1] + "=" * (-len(parts[1]) % 4)
                return json.loads(base64.urlsafe_b64decode(pad))
            except Exception as exc:
                raise ValueError(f"Invalid token: {exc}") from exc
        raise ValueError("Malformed token")
    except Exception as exc:
        raise ValueError(str(exc)) from exc


# ---------------------------------------------------------------------------
# In-memory user store (replace with DB in production)
# ---------------------------------------------------------------------------

_USERS: dict[str, dict[str, Any]] = {}  # user_id -> user record
_DEVICE_TOKENS: dict[str, list[dict[str, Any]]] = {}  # user_id -> list of device tokens


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def _ok(data: Any, request_id: str, started: float) -> dict[str, Any]:
    return {
        "data": data,
        "error": None,
        "meta": {
            "request_id": request_id,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }


def _err(message: str, request_id: str, started: float) -> dict[str, Any]:
    return {
        "data": None,
        "error": message,
        "meta": {
            "request_id": request_id,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        },
    }


# ---------------------------------------------------------------------------
# Pydantic request/response models
# ---------------------------------------------------------------------------

if _PYDANTIC_AVAILABLE:
    class RegisterRequest(BaseModel):
        email: str
        name: str
        password: str

    class LoginRequest(BaseModel):
        email: str
        password: str

    class RefreshRequest(BaseModel):
        refresh_token: str

    class RunRequest(BaseModel):
        task: str
        agent_type: str = "monolithic"
        context: dict[str, Any] = Field(default_factory=dict)
        model: str = "gpt-4o"
        stream: bool = False

    class QueryRequest(BaseModel):
        prompt: str
        model: str = "gpt-4o"
        system: str = ""
        temperature: float = 0.7
        max_tokens: int = 2048

    class CheckoutRequest(BaseModel):
        tier: str
        success_url: str
        cancel_url: str

    class PortalRequest(BaseModel):
        return_url: str

    class MemorySearchRequest(BaseModel):
        query: str
        limit: int = 10
        filters: dict[str, Any] = Field(default_factory=dict)

    class MemoryStoreRequest(BaseModel):
        content: str
        metadata: dict[str, Any] = Field(default_factory=dict)
        tags: list[str] = Field(default_factory=list)

    class PushRegisterRequest(BaseModel):
        device_token: str
        platform: str  # "apns" | "fcm"
        device_id: str

    class PushSendRequest(BaseModel):
        user_id: str
        title: str
        body: str
        data: dict[str, Any] = Field(default_factory=dict)
else:
    # Stub classes for when Pydantic is unavailable
    class RegisterRequest: ...         # type: ignore[no-redef]
    class LoginRequest: ...            # type: ignore[no-redef]
    class RefreshRequest: ...          # type: ignore[no-redef]
    class RunRequest: ...              # type: ignore[no-redef]
    class QueryRequest: ...            # type: ignore[no-redef]
    class CheckoutRequest: ...         # type: ignore[no-redef]
    class PortalRequest: ...           # type: ignore[no-redef]
    class MemorySearchRequest: ...     # type: ignore[no-redef]
    class MemoryStoreRequest: ...      # type: ignore[no-redef]
    class PushRegisterRequest: ...     # type: ignore[no-redef]
    class PushSendRequest: ...         # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# create_production_app
# ---------------------------------------------------------------------------

def create_production_app(config: APIConfig | None = None) -> Any:
    """
    Build and return the production FastAPI application.

    Raises:
        ImportError: if FastAPI is not installed.
    """
    if not _FASTAPI_AVAILABLE:
        raise ImportError(
            "FastAPI is required to create the production app. "
            "Install it with: pip install fastapi uvicorn"
        )

    if config is None:
        config = APIConfig()

    # ------------------------------------------------------------------
    # App initialisation
    # ------------------------------------------------------------------
    app = FastAPI(
        title="Horizon Orchestra API",
        version=config.api_version,
        docs_url="/docs" if config.enable_docs else None,
        redoc_url="/redoc" if config.enable_docs else None,
        openapi_url=f"/{config.api_version}/openapi.json" if config.enable_docs else None,
    )

    # ── Rate limiting middleware ──────────────────────────────────────
    import time as _time
    import collections
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import Response as StarletteResponse

    _rate_windows: dict = {}
    _RATE_LIMIT = int(os.environ.get("ORCHESTRA_RATE_LIMIT", "100"))   # req/min per IP
    _RATE_WINDOW = 60  # seconds

    class RateLimitMiddleware(BaseHTTPMiddleware):
        """Sliding-window rate limiter per IP. Returns 429 on excess."""
        async def dispatch(self, request: Request, call_next: Any) -> Any:
            ip = request.client.host if request.client else "unknown"
            now = _time.monotonic()
            window = _rate_windows.setdefault(ip, collections.deque())
            # Remove entries outside the window
            while window and now - window[0] > _RATE_WINDOW:
                window.popleft()
            if len(window) >= _RATE_LIMIT:
                return StarletteResponse(
                    content='{"error":{"code":"RATE_LIMIT_EXCEEDED","message":"Too many requests"},"data":null,"meta":{}}',
                    status_code=429,
                    media_type="application/json",
                    headers={"Retry-After": str(_RATE_WINDOW)},
                )
            window.append(now)
            return await call_next(request)

    app.add_middleware(RateLimitMiddleware)

    # ── Request ID + timing middleware ────────────────────────────────
    class RequestMetaMiddleware(BaseHTTPMiddleware):
        """Attaches X-Request-ID and X-Response-Time to every response."""
        async def dispatch(self, request: Request, call_next: Any) -> Any:
            req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())[:8]
            request.state.request_id = req_id
            t0 = _time.monotonic()
            response = await call_next(request)
            elapsed = round((_time.monotonic() - t0) * 1000, 1)
            response.headers["X-Request-ID"] = req_id
            response.headers["X-Response-Time"] = f"{elapsed}ms"
            response.headers["X-Powered-By"] = "Horizon Orchestra"
            return response

    app.add_middleware(RequestMetaMiddleware)

    # ── Security headers middleware ───────────────────────────────────
    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        """Adds hardened HTTP security headers to every response."""
        async def dispatch(self, request: Request, call_next: Any) -> Any:
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; object-src 'none'; frame-ancestors 'none'"
            )
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # Initialise sub-systems (with graceful fallback)
    # ------------------------------------------------------------------
    billing: StripeBilling | None = None
    if _BILLING_AVAILABLE:
        try:
            billing = StripeBilling(BillingConfig())
            logger.info("StripeBilling initialised")
        except Exception as exc:  # noqa: BLE001
            logger.warning("StripeBilling init failed: %s", exc)

    security: SecurityHardening | None = None
    if _SECURITY_AVAILABLE and config.enable_security:
        try:
            security = SecurityHardening(SecurityConfig())
            security.middleware(app)
            logger.info("SecurityHardening middleware installed")
        except Exception as exc:  # noqa: BLE001
            logger.warning("SecurityHardening init failed: %s", exc)

    # ------------------------------------------------------------------
    # Auth dependency
    # ------------------------------------------------------------------
    async def get_current_user(
        authorization: str = Header(default=""),
    ) -> dict[str, Any]:
        """Extract and validate the Bearer JWT from the Authorization header."""
        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token",
            )
        try:
            payload = _decode_jwt(token, config.jwt_secret, config.jwt_algorithm)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {exc}",
            ) from exc
        user_id = payload.get("sub")
        user = _USERS.get(user_id, {})
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found",
            )
        return user

    async def get_admin_user(
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        if not current_user.get("is_admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        return current_user

    # ------------------------------------------------------------------
    # Billing limit check helper
    # ------------------------------------------------------------------
    async def check_billing_limits(user_id: str) -> None:
        """Raise 429 if the user has exceeded their tier limits."""
        if billing is None:
            return
        result = await billing.check_limits(user_id)
        if not result["allowed"]:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=result["reason"],
            )

    # ------------------------------------------------------------------
    # Request context helper
    # ------------------------------------------------------------------
    def _ctx(request: Request) -> tuple[str, float]:
        """Return (request_id, perf_counter_start)."""
        req_id = str(uuid.uuid4())
        return req_id, time.perf_counter()

    # ==================================================================
    # AUTH ENDPOINTS
    # ==================================================================

    @app.post(f"/{config.api_version}/auth/register")
    async def register(body: RegisterRequest, request: Request) -> dict[str, Any]:
        """Create a new account and (optionally) a Stripe customer."""
        req_id, started = _ctx(request)
        import hashlib

        # Check for existing user
        existing = next(
            (u for u in _USERS.values() if u.get("email") == body.email), None
        )
        if existing:
            return JSONResponse(
                status_code=400,
                content=_err("Email already registered", req_id, started),
            )

        user_id = str(uuid.uuid4())
        password_hash = hashlib.sha256(body.password.encode()).hexdigest()
        user_record: dict[str, Any] = {
            "id": user_id,
            "email": body.email,
            "name": body.name,
            "password_hash": password_hash,
            "is_admin": False,
            "stripe_customer_id": None,
            "created_at": time.time(),
        }

        # Create Stripe customer
        if billing:
            try:
                customer = await billing.create_customer(user_id, body.email, body.name)
                user_record["stripe_customer_id"] = customer["id"]
                # Provision free tier subscription
                await billing.create_subscription(
                    user_id, "free", customer["id"]
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Stripe customer creation failed: %s", exc)

        _USERS[user_id] = user_record

        token = _make_jwt(
            {"sub": user_id, "email": body.email},
            config.jwt_secret,
            config.jwt_algorithm,
            config.jwt_expire_minutes,
        )
        refresh = _make_jwt(
            {"sub": user_id, "type": "refresh"},
            config.jwt_secret,
            config.jwt_algorithm,
            expire_minutes=60 * 24 * 30,
        )

        logger.info("New user registered: %s", user_id)
        return _ok(
            {
                "user_id": user_id,
                "access_token": token,
                "refresh_token": refresh,
                "token_type": "Bearer",
            },
            req_id,
            started,
        )

    @app.post(f"/{config.api_version}/auth/login")
    async def login(body: LoginRequest, request: Request) -> dict[str, Any]:
        """Authenticate and issue JWT tokens."""
        import hashlib
        req_id, started = _ctx(request)

        user = next(
            (u for u in _USERS.values() if u.get("email") == body.email), None
        )
        if not user:
            return JSONResponse(
                status_code=401,
                content=_err("Invalid email or password", req_id, started),
            )

        pw_hash = hashlib.sha256(body.password.encode()).hexdigest()
        if user.get("password_hash") != pw_hash:
            if security:
                security.audit.log(
                    "auth_failure", user["id"], "login",
                    {"email": body.email}, severity="medium",
                )
            return JSONResponse(
                status_code=401,
                content=_err("Invalid email or password", req_id, started),
            )

        if security:
            security.audit.log("auth_success", user["id"], "login", {})

        access_token = _make_jwt(
            {"sub": user["id"], "email": user["email"]},
            config.jwt_secret,
            config.jwt_algorithm,
            config.jwt_expire_minutes,
        )
        refresh_token = _make_jwt(
            {"sub": user["id"], "type": "refresh"},
            config.jwt_secret,
            config.jwt_algorithm,
            expire_minutes=60 * 24 * 30,
        )

        return _ok(
            {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_type": "Bearer",
            },
            req_id,
            started,
        )

    @app.post(f"/{config.api_version}/auth/refresh")
    async def refresh_token(body: RefreshRequest, request: Request) -> dict[str, Any]:
        """Issue a new access token from a valid refresh token."""
        req_id, started = _ctx(request)
        try:
            payload = _decode_jwt(
                body.refresh_token, config.jwt_secret, config.jwt_algorithm
            )
        except ValueError as exc:
            return JSONResponse(
                status_code=401,
                content=_err(f"Invalid refresh token: {exc}", req_id, started),
            )

        if payload.get("type") != "refresh":
            return JSONResponse(
                status_code=401,
                content=_err("Token is not a refresh token", req_id, started),
            )

        user_id = payload.get("sub")
        user = _USERS.get(user_id)
        if not user:
            return JSONResponse(
                status_code=401,
                content=_err("User not found", req_id, started),
            )

        new_access = _make_jwt(
            {"sub": user_id, "email": user.get("email", "")},
            config.jwt_secret,
            config.jwt_algorithm,
            config.jwt_expire_minutes,
        )
        return _ok(
            {"access_token": new_access, "token_type": "Bearer"},
            req_id,
            started,
        )


    # ── Guardian singletons (policy + audit for all API routes) ───────────────
    try:
        from ..guardian.policy_engine import PolicyEngine as _PECls
        from ..guardian.audit_ledger import AuditLedger as _APILedger
        from ..guardian.beyond_guardrails import BeyondGuardrails as _APIBG
        _POLICY_ENGINE = _PECls()
        _API_AUDIT_LEDGER = _APILedger()
        _API_GUARDRAILS = _APIBG()
        _API_GUARDIAN_ACTIVE = True
    except Exception:
        _POLICY_ENGINE = _API_AUDIT_LEDGER = _API_GUARDRAILS = None  # type: ignore
        _API_GUARDIAN_ACTIVE = False

    @app.get(f"/{config.api_version}/auth/me")
    async def get_me(
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Return the authenticated user's profile + subscription info."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]
        profile = {k: v for k, v in current_user.items() if k != "password_hash"}

        if billing:
            try:
                sub = await billing.get_subscription(user_id)
                if sub:
                    profile["subscription"] = {
                        "tier": sub.tier,
                        "status": sub.status,
                        "current_period_end": sub.current_period_end.isoformat(),
                        "cancel_at_period_end": sub.cancel_at_period_end,
                    }
            except Exception as exc:  # noqa: BLE001
                logger.warning("get_me billing lookup failed: %s", exc)

        return _ok(profile, req_id, started)

    # ==================================================================
    # CORE ENDPOINTS
    # ==================================================================

    @app.post(f"/{config.api_version}/run")
    async def run_task(
        body: RunRequest,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Execute a task through the agent system."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]

        await check_billing_limits(user_id)

        # Record usage
        if billing:
            await billing.record_usage(user_id, requests=1)

        # Try to import and use agent system
        result: dict[str, Any] = {}
        try:
            from ..agents.monolithic_agent import MonolithicAgent  # type: ignore[import]
            agent = MonolithicAgent()
            result = await agent.run(body.task, context=body.context)
        except ImportError:
            # Stub response when agent system not available
            result = {
                "output": f"[Stub] Task received: {body.task}",
                "agent_type": body.agent_type,
                "model": body.model,
                "status": "completed",
            }
        except Exception as exc:  # noqa: BLE001
            logger.error("run_task error: %s", exc)
            return JSONResponse(
                status_code=500,
                content=_err(str(exc), req_id, started),
            )

        if billing:
            # Estimate token usage from output length
            output_str = str(result.get("output", ""))
            estimated_tokens = len(output_str.split()) * 4 // 3
            await billing.record_usage(user_id, tokens=estimated_tokens)

        return _ok(result, req_id, started)

    @app.websocket(f"/{config.api_version}/stream")
    async def stream_ws(websocket: WebSocket) -> None:
        """WebSocket endpoint for streaming agent responses."""
        await websocket.accept()
        try:
            while True:
                data = await websocket.receive_json()
                task = data.get("task", "")
                user_id = data.get("user_id", "")

                if billing and user_id:
                    result = await billing.check_limits(user_id)
                    if not result["allowed"]:
                        await websocket.send_json(
                            {"error": result["reason"], "done": True}
                        )
                        continue

                # Stream response in chunks
                response_text = f"Processing task: {task}"
                words = response_text.split()
                for i, word in enumerate(words):
                    await websocket.send_json(
                        {
                            "chunk": word + (" " if i < len(words) - 1 else ""),
                            "done": i == len(words) - 1,
                            "request_id": str(uuid.uuid4()),
                        }
                    )
                    import asyncio
                    await asyncio.sleep(0.05)

                if billing and user_id:
                    await billing.record_usage(user_id, requests=1, tokens=len(words))

        except WebSocketDisconnect:
            logger.debug("WebSocket client disconnected")
        except Exception as exc:  # noqa: BLE001
            logger.error("WebSocket error: %s", exc)
            try:
                await websocket.send_json({"error": str(exc), "done": True})
            except Exception:
                                import logging as _log; _log.getLogger('api.server').debug('Suppressed exception', exc_info=True)

    @app.post(f"/{config.api_version}/query")
    async def query_model(
        body: QueryRequest,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Direct model query (bypasses agent orchestration)."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]

        await check_billing_limits(user_id)
        if billing:
            await billing.record_usage(user_id, requests=1)

        # Attempt real model call
        response_text = ""
        try:
            import httpx
            headers = {"Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}"}
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": body.model,
                        "messages": [
                            *(
                                [{"role": "system", "content": body.system}]
                                if body.system
                                else []
                            ),
                            {"role": "user", "content": body.prompt},
                        ],
                        "temperature": body.temperature,
                        "max_tokens": body.max_tokens,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    response_text = (
                        data["choices"][0]["message"]["content"]
                        if data.get("choices")
                        else ""
                    )
                else:
                    response_text = f"[Model API error {resp.status_code}]"
        except Exception as exc:  # noqa: BLE001
            logger.warning("Model query failed: %s", exc)
            response_text = f"[Stub response for: {body.prompt[:80]}]"

        if billing:
            token_estimate = len(response_text.split()) * 4 // 3
            await billing.record_usage(user_id, tokens=token_estimate)

        # Check response for PII
        if security:
            sec_resp = await security.check_response(response_text)
            if sec_resp.blocked:
                response_text = "[Response redacted: contains sensitive data]"

        return _ok(
            {
                "response": response_text,
                "model": body.model,
                "tokens_used": len(response_text.split()) * 4 // 3,
            },
            req_id,
            started,
        )

    # ==================================================================
    # BILLING ENDPOINTS
    # ==================================================================

    @app.post(f"/{config.api_version}/billing/checkout")
    async def billing_checkout(
        body: CheckoutRequest,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Create a Stripe Checkout session for plan upgrade."""
        req_id, started = _ctx(request)
        if not billing:
            return JSONResponse(
                status_code=503,
                content=_err("Billing system unavailable", req_id, started),
            )
        user_id = current_user["id"]
        customer_id = current_user.get("stripe_customer_id")
        if not customer_id:
            try:
                customer = await billing.create_customer(
                    user_id, current_user["email"], current_user["name"]
                )
                customer_id = customer["id"]
                _USERS[user_id]["stripe_customer_id"] = customer_id
            except Exception as exc:  # noqa: BLE001
                return JSONResponse(
                    status_code=500,
                    content=_err(f"Could not create Stripe customer: {exc}", req_id, started),
                )

        try:
            session = await billing.create_checkout_session(
                user_id, body.tier, body.success_url, body.cancel_url
            )
            return _ok(
                {"checkout_url": session.get("url"), "session_id": session.get("id")},
                req_id,
                started,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                status_code=500,
                content=_err(str(exc), req_id, started),
            )

    @app.post(f"/{config.api_version}/billing/portal")
    async def billing_portal(
        body: PortalRequest,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Create a Stripe Customer Portal session for self-service plan management."""
        req_id, started = _ctx(request)
        if not billing:
            return JSONResponse(
                status_code=503,
                content=_err("Billing system unavailable", req_id, started),
            )
        stripe_customer_id = current_user.get("stripe_customer_id")
        if not stripe_customer_id:
            return JSONResponse(
                status_code=400,
                content=_err("No Stripe customer linked to this account", req_id, started),
            )
        try:
            session = await billing.create_portal_session(
                stripe_customer_id, body.return_url
            )
            return _ok({"portal_url": session.get("url")}, req_id, started)
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                status_code=500,
                content=_err(str(exc), req_id, started),
            )

    @app.get(f"/{config.api_version}/billing/subscription")
    async def get_subscription(
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Return the current subscription details."""
        req_id, started = _ctx(request)
        if not billing:
            return _ok({"tier": "free", "status": "active"}, req_id, started)
        user_id = current_user["id"]
        sub = await billing.get_subscription(user_id)
        if not sub:
            return _ok({"tier": "free", "status": "none"}, req_id, started)
        return _ok(
            {
                "id": sub.id,
                "tier": sub.tier,
                "status": sub.status,
                "stripe_subscription_id": sub.stripe_subscription_id,
                "current_period_start": sub.current_period_start.isoformat(),
                "current_period_end": sub.current_period_end.isoformat(),
                "cancel_at_period_end": sub.cancel_at_period_end,
                "created_at": sub.created_at.isoformat(),
            },
            req_id,
            started,
        )

    @app.get(f"/{config.api_version}/billing/usage")
    async def get_usage(
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Return current usage vs tier limits."""
        req_id, started = _ctx(request)
        if not billing:
            return _ok({"usage": {}, "limits": {}, "allowed": True}, req_id, started)
        user_id = current_user["id"]
        result = await billing.check_limits(user_id)
        return _ok(result, req_id, started)

    @app.get(f"/{config.api_version}/billing/invoices")
    async def get_invoices(
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Return the last 10 invoices."""
        req_id, started = _ctx(request)
        if not billing:
            return _ok([], req_id, started)
        user_id = current_user["id"]
        invoices = await billing.get_invoices(user_id, limit=10)
        return _ok(
            [
                {
                    "id": inv.id,
                    "stripe_invoice_id": inv.stripe_invoice_id,
                    "amount": inv.amount,
                    "currency": inv.currency,
                    "status": inv.status,
                    "period_start": inv.period_start.isoformat(),
                    "period_end": inv.period_end.isoformat(),
                    "line_items": inv.line_items,
                    "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
                    "pdf_url": inv.pdf_url,
                }
                for inv in invoices
            ],
            req_id,
            started,
        )

    @app.post(config.stripe_webhook_path)
    async def stripe_webhook(request: Request) -> dict[str, Any]:
        """Handle inbound Stripe webhook events. No auth required."""
        req_id, started = _ctx(request)
        if not billing:
            return _ok({"status": "ignored"}, req_id, started)

        payload = await request.body()
        signature = request.headers.get("stripe-signature", "")

        try:
            result = await billing.handle_webhook(payload, signature)
            return _ok(result, req_id, started)
        except Exception as exc:  # noqa: BLE001
            logger.error("Webhook handling error: %s", exc)
            return JSONResponse(
                status_code=400,
                content=_err(str(exc), req_id, started),
            )

    # ==================================================================
    # MEMORY ENDPOINTS
    # ==================================================================

    # In-memory store for demo purposes
    _MEMORIES: dict[str, list[dict[str, Any]]] = {}

    @app.post(f"/{config.api_version}/memory/search")
    async def memory_search(
        body: MemorySearchRequest,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Search memories via semantic or keyword matching."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]

        # Try MemoryStore if available
        try:
            from ..memory.store import MemoryStore  # type: ignore[import]
            store = MemoryStore()
            results = await store.search(user_id, body.query, limit=body.limit)
            return _ok(results, req_id, started)
        except ImportError:
                        import logging as _log; _log.getLogger('api.server').debug('Suppressed exception', exc_info=True)

        # Fallback: simple substring search over in-memory list
        user_memories = _MEMORIES.get(user_id, [])
        query_lower = body.query.lower()
        matched = [
            m for m in user_memories
            if query_lower in m.get("content", "").lower()
        ]
        return _ok(matched[: body.limit], req_id, started)

    @app.post(f"/{config.api_version}/memory/store")
    async def memory_store(
        body: MemoryStoreRequest,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Store a memory entry."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]

        memory_id = str(uuid.uuid4())
        entry = {
            "id": memory_id,
            "content": body.content,
            "metadata": body.metadata,
            "tags": body.tags,
            "created_at": time.time(),
        }

        try:
            from ..memory.store import MemoryStore  # type: ignore[import]
            store = MemoryStore()
            await store.store(user_id, entry)
        except ImportError:
            if user_id not in _MEMORIES:
                _MEMORIES[user_id] = []
            _MEMORIES[user_id].append(entry)

        return _ok({"id": memory_id}, req_id, started)

    @app.get(f"/{config.api_version}/memory/list")
    async def memory_list(
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """List all memories for the current user."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]

        try:
            from ..memory.store import MemoryStore  # type: ignore[import]
            store = MemoryStore()
            memories = await store.list(user_id)
            return _ok(memories, req_id, started)
        except ImportError:
            return _ok(_MEMORIES.get(user_id, []), req_id, started)

    # ==================================================================
    # FILE ENDPOINTS
    # ==================================================================

    _WORKSPACE_ROOT = os.environ.get("WORKSPACE_ROOT", "/tmp/horizon_workspace")

    @app.post(f"/{config.api_version}/files/upload")
    async def file_upload(
        request: Request,
        file: UploadFile = File(...),
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Upload a file to the user's workspace."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]
        user_dir = os.path.join(_WORKSPACE_ROOT, user_id)
        os.makedirs(user_dir, exist_ok=True)

        # Sanitise filename
        safe_name = os.path.basename(file.filename or "upload")
        dest_path = os.path.join(user_dir, safe_name)

        content = await file.read()
        max_bytes = config.max_request_size_mb * 1024 * 1024
        if len(content) > max_bytes:
            return JSONResponse(
                status_code=413,
                content=_err(
                    f"File exceeds maximum size of {config.max_request_size_mb}MB",
                    req_id, started,
                ),
            )

        with open(dest_path, "wb") as fh:
            fh.write(content)

        logger.info("File uploaded: user=%s file=%s size=%d", user_id, safe_name, len(content))
        return _ok(
            {"filename": safe_name, "size_bytes": len(content), "path": dest_path},
            req_id, started,
        )

    @app.get(f"/{config.api_version}/files/list")
    async def file_list(
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """List files in the user's workspace."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]
        user_dir = os.path.join(_WORKSPACE_ROOT, user_id)
        os.makedirs(user_dir, exist_ok=True)

        files = []
        for fname in os.listdir(user_dir):
            fpath = os.path.join(user_dir, fname)
            if os.path.isfile(fpath):
                stat = os.stat(fpath)
                files.append({
                    "filename": fname,
                    "size_bytes": stat.st_size,
                    "modified_at": stat.st_mtime,
                })

        return _ok(sorted(files, key=lambda f: f["modified_at"], reverse=True), req_id, started)

    @app.get(f"/{config.api_version}/files/{{filename}}")
    async def file_download(
        filename: str,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> Any:
        """Download a specific file."""
        from fastapi.responses import FileResponse

        user_id = current_user["id"]
        safe_name = os.path.basename(filename)
        fpath = os.path.join(_WORKSPACE_ROOT, user_id, safe_name)

        if not os.path.isfile(fpath):
            raise HTTPException(status_code=404, detail="File not found")

        return FileResponse(fpath, filename=safe_name)

    @app.get(f"/{config.api_version}/files/{{filename}}/share")
    async def file_share(
        filename: str,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Generate a presigned download URL for a workspace file."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]
        safe_name = os.path.basename(filename)
        fpath = os.path.join(_WORKSPACE_ROOT, user_id, safe_name)

        if not os.path.isfile(fpath):
            return JSONResponse(
                status_code=404,
                content=_err("File not found", req_id, started),
            )

        # Try S3 presigned URL
        try:
            import boto3
            s3 = boto3.client("s3")
            bucket = os.environ.get("S3_WORKSPACE_BUCKET", "horizon-workspace")
            key = f"{user_id}/{safe_name}"
            url = s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=3600,
            )
            return _ok({"url": url, "expires_in": 3600}, req_id, started)
        except Exception:  # noqa: BLE001
            # Fallback: return a local download URL
            base_url = str(request.base_url).rstrip("/")
            url = f"{base_url}/{config.api_version}/files/{safe_name}"
            return _ok({"url": url, "expires_in": None, "note": "Direct URL (S3 unavailable)"}, req_id, started)

    # ==================================================================
    # MODELS ENDPOINT
    # ==================================================================

    @app.get(f"/{config.api_version}/models")
    async def list_models(
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """List available AI models."""
        req_id, started = _ctx(request)
        models = [
            {"id": "gpt-4o", "provider": "openai", "context_window": 128000, "supports_vision": True},
            {"id": "gpt-4o-mini", "provider": "openai", "context_window": 128000, "supports_vision": True},
            {"id": "gpt-4-turbo", "provider": "openai", "context_window": 128000, "supports_vision": True},
            {"id": "claude-3-5-sonnet-20241022", "provider": "anthropic", "context_window": 200000, "supports_vision": True},
            {"id": "claude-3-5-haiku-20241022", "provider": "anthropic", "context_window": 200000, "supports_vision": True},
            {"id": "claude-3-opus-20240229", "provider": "anthropic", "context_window": 200000, "supports_vision": True},
            {"id": "gemini-2.0-flash", "provider": "google", "context_window": 1000000, "supports_vision": True},
            {"id": "gemini-1.5-pro", "provider": "google", "context_window": 2000000, "supports_vision": True},
            {"id": "mistral-large-latest", "provider": "mistral", "context_window": 128000, "supports_vision": False},
            {"id": "llama-3.3-70b-versatile", "provider": "groq", "context_window": 128000, "supports_vision": False},
        ]
        return _ok(models, req_id, started)

    # ==================================================================
    # CONNECTOR ENDPOINTS
    # ==================================================================

    @app.get(f"/{config.api_version}/connectors")
    async def list_connectors(
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """List available and connected connectors."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]

        try:
            from ..connectors.registry import ConnectorRegistry  # type: ignore[import]
            registry = ConnectorRegistry()
            connectors = await registry.list(user_id)
            return _ok(connectors, req_id, started)
        except ImportError:
            # Return a static connector catalogue
            connectors = [
                {"name": "gmail", "display_name": "Gmail", "status": "disconnected", "category": "email"},
                {"name": "google_drive", "display_name": "Google Drive", "status": "disconnected", "category": "storage"},
                {"name": "notion", "display_name": "Notion", "status": "disconnected", "category": "productivity"},
                {"name": "slack", "display_name": "Slack", "status": "disconnected", "category": "communication"},
                {"name": "github", "display_name": "GitHub", "status": "disconnected", "category": "development"},
                {"name": "stripe", "display_name": "Stripe", "status": "connected", "category": "payments"},
            ]
            return _ok(connectors, req_id, started)

    @app.post(f"/{config.api_version}/connectors/{{name}}/connect")
    async def connect_connector(
        name: str,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Initiate OAuth connection for a connector."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]

        try:
            from ..connectors.registry import ConnectorRegistry  # type: ignore[import]
            registry = ConnectorRegistry()
            result = await registry.connect(user_id, name)
            return _ok(result, req_id, started)
        except ImportError:
            oauth_url = f"https://oauth.horizonorchestra.ai/connect/{name}?user_id={user_id}"
            return _ok(
                {"oauth_url": oauth_url, "connector": name, "status": "pending"},
                req_id, started,
            )

    # ==================================================================
    # ADMIN ENDPOINTS
    # ==================================================================

    @app.get(f"/{config.api_version}/admin/users")
    async def admin_list_users(
        request: Request,
        admin: dict[str, Any] = Depends(get_admin_user),
    ) -> dict[str, Any]:
        """List all users (admin only)."""
        req_id, started = _ctx(request)
        users = [
            {k: v for k, v in u.items() if k != "password_hash"}
            for u in _USERS.values()
        ]
        return _ok({"users": users, "total": len(users)}, req_id, started)

    @app.get(f"/{config.api_version}/admin/usage")
    async def admin_usage_stats(
        request: Request,
        admin: dict[str, Any] = Depends(get_admin_user),
    ) -> dict[str, Any]:
        """Return system-wide usage statistics (admin only)."""
        req_id, started = _ctx(request)
        if not billing:
            return _ok({"error": "Billing unavailable"}, req_id, started)

        total_requests = 0
        total_tokens = 0
        user_stats = []

        for uid in _USERS:
            try:
                meter = billing._usage.get(uid)
                if meter:
                    total_requests += meter.requests_used
                    total_tokens += meter.tokens_used
                    user_stats.append({
                        "user_id": uid,
                        "requests_used": meter.requests_used,
                        "tokens_used": meter.tokens_used,
                        "agents_spawned": meter.agents_spawned,
                    })
            except Exception:  # noqa: BLE001
                pass

        return _ok(
            {
                "total_users": len(_USERS),
                "total_requests": total_requests,
                "total_tokens": total_tokens,
                "user_breakdown": user_stats,
            },
            req_id, started,
        )

    @app.get(f"/{config.api_version}/admin/health")
    async def admin_health(
        request: Request,
        admin: dict[str, Any] = Depends(get_admin_user),
    ) -> dict[str, Any]:
        """System health check (admin only)."""
        req_id, started = _ctx(request)
        health = {
            "status": "healthy",
            "api_version": config.api_version,
            "billing_available": billing is not None,
            "security_available": security is not None,
            "uptime_s": round(time.perf_counter(), 1),
            "users_loaded": len(_USERS),
        }
        if security:
            blocked_ips = security.ddos.get_blocked_ips()
            health["blocked_ips"] = len(blocked_ips)
            health["audit_events"] = len(security.audit._trail)

        return _ok(health, req_id, started)

    # ==================================================================
    # PUSH NOTIFICATION ENDPOINTS
    # ==================================================================

    @app.post(f"/{config.api_version}/push/register")
    async def push_register(
        body: PushRegisterRequest,
        request: Request,
        current_user: dict[str, Any] = Depends(get_current_user),
    ) -> dict[str, Any]:
        """Register a device token for push notifications (APNs / FCM)."""
        req_id, started = _ctx(request)
        user_id = current_user["id"]

        if user_id not in _DEVICE_TOKENS:
            _DEVICE_TOKENS[user_id] = []

        # Deduplicate by device_id
        _DEVICE_TOKENS[user_id] = [
            t for t in _DEVICE_TOKENS[user_id] if t.get("device_id") != body.device_id
        ]
        _DEVICE_TOKENS[user_id].append({
            "device_token": body.device_token,
            "platform": body.platform,
            "device_id": body.device_id,
            "registered_at": time.time(),
        })

        logger.info(
            "Push token registered: user=%s platform=%s", user_id, body.platform
        )
        return _ok({"registered": True, "platform": body.platform}, req_id, started)

    @app.post(f"/{config.api_version}/push/send")
    async def push_send(
        body: PushSendRequest,
        request: Request,
        admin: dict[str, Any] = Depends(get_admin_user),
    ) -> dict[str, Any]:
        """
        Send a push notification to a user's registered devices (admin only).

        Supports APNs (iOS) and FCM (Android / web).
        """
        req_id, started = _ctx(request)
        user_id = body.user_id
        devices = _DEVICE_TOKENS.get(user_id, [])

        if not devices:
            return _ok(
                {"sent": 0, "message": "No registered devices for this user"},
                req_id, started,
            )

        sent = 0
        errors = []

        for device in devices:
            platform = device.get("platform", "")
            token = device.get("device_token", "")

            try:
                if platform == "fcm":
                    await _send_fcm(token, body.title, body.body, body.data)
                    sent += 1
                elif platform == "apns":
                    await _send_apns(token, body.title, body.body, body.data)
                    sent += 1
                else:
                    errors.append(f"Unknown platform: {platform}")
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
                logger.warning(
                    "Push send failed: user=%s platform=%s error=%s",
                    user_id, platform, exc,
                )

        return _ok(
            {"sent": sent, "total_devices": len(devices), "errors": errors},
            req_id, started,
        )

    # ==================================================================
    # Global error handler
    # ==================================================================

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        req_id = str(uuid.uuid4())
        logger.exception("Unhandled exception in request %s: %s", req_id, exc)
        return JSONResponse(
            status_code=500,
            content={
                "data": None,
                "error": "Internal server error",
                "meta": {"request_id": req_id, "duration_ms": 0},
            },
        )

    logger.info(
        "Horizon Orchestra API ready on %s:%d (docs=%s)",
        config.host, config.port, config.enable_docs,
    )
    return app


# ---------------------------------------------------------------------------
# Push notification senders (stubbed; replace with real APNs/FCM SDKs)
# ---------------------------------------------------------------------------

async def _send_fcm(
    device_token: str, title: str, body: str, data: dict[str, Any]
) -> None:
    """Send a push notification via FCM HTTP v1 API."""
    fcm_key = os.environ.get("FCM_SERVER_KEY", "")
    if not fcm_key:
        logger.warning("FCM_SERVER_KEY not set — push not delivered")
        return

    import httpx
    payload = {
        "message": {
            "token": device_token,
            "notification": {"title": title, "body": body},
            "data": {k: str(v) for k, v in data.items()},
        }
    }
    project_id = os.environ.get("FCM_PROJECT_ID", "horizon-orchestra")
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"https://fcm.googleapis.com/v1/projects/{project_id}/messages:send",
            headers={"Authorization": f"Bearer {fcm_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"FCM error {resp.status_code}: {resp.text[:200]}")


async def _send_apns(
    device_token: str, title: str, body: str, data: dict[str, Any]
) -> None:
    """Send a push notification via Apple Push Notification service (APNs)."""
    apns_key = os.environ.get("APNS_AUTH_KEY", "")
    bundle_id = os.environ.get("APNS_BUNDLE_ID", "ai.horizonorchestra.app")
    team_id = os.environ.get("APNS_TEAM_ID", "")
    key_id = os.environ.get("APNS_KEY_ID", "")

    if not apns_key:
        logger.warning("APNS_AUTH_KEY not set — push not delivered")
        return

    try:
        import jwt as pyjwt
        import time as _time
        now = int(_time.time())
        token = pyjwt.encode(
            {"iss": team_id, "iat": now},
            apns_key,
            algorithm="ES256",
            headers={"kid": key_id},
        )
    except ImportError:
        logger.warning("PyJWT not installed — cannot generate APNs token")
        return

    import httpx
    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
        },
        **data,
    }
    use_sandbox = os.environ.get("APNS_SANDBOX", "true").lower() == "true"
    host = "api.sandbox.push.apple.com" if use_sandbox else "api.push.apple.com"

    async with httpx.AsyncClient(http2=True, timeout=10) as client:
        resp = await client.post(
            f"https://{host}/3/device/{device_token}",
            headers={
                "authorization": f"bearer {token}",
                "apns-topic": bundle_id,
                "apns-push-type": "alert",
            },
            json=payload,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"APNs error {resp.status_code}: {resp.text[:200]}")


# ---------------------------------------------------------------------------
# ProductionAPI class (wrapper for lifecycle management)
# ---------------------------------------------------------------------------

class ProductionAPI:
    """
    Lifecycle wrapper around the FastAPI app.

    Example usage::

        config = APIConfig(host="0.0.0.0", port=8000)
        api = ProductionAPI(config)
        api.start()          # blocking
        # or
        await api.start_async()
    """

    def __init__(self, config: APIConfig | None = None) -> None:
        self._config = config or APIConfig()
        self._app: Any = None

    @property
    def app(self) -> Any:
        if self._app is None:
            self._app = create_production_app(self._config)
        return self._app

    def start(self) -> None:
        """Start the server synchronously (blocking)."""
        if not _FASTAPI_AVAILABLE:
            raise ImportError("FastAPI and uvicorn are required to start the server.")
        uvicorn.run(
            self.app,
            host=self._config.host,
            port=self._config.port,
            log_level="info",
        )

    async def start_async(self) -> None:
        """Start the server asynchronously."""
        if not _FASTAPI_AVAILABLE:
            raise ImportError("FastAPI and uvicorn are required to start the server.")
        cfg = uvicorn.Config(
            self.app,
            host=self._config.host,
            port=self._config.port,
            log_level="info",
        )
        server = uvicorn.Server(cfg)
        await server.serve()
