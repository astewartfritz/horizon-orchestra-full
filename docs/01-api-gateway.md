# API Gateway — Production Middleware Stack

> **Module:** `src/code_agent/api_gateway/` — 31 tests

The API Gateway provides a production-grade middleware pipeline for all Orchestra API traffic. It stacks rate limiting, authentication, validation, logging, and tracing in a single FastAPI application.

---

## Middleware Pipeline (Outer → Inner)

```
Request
  │
  ▼
┌──────────────────────────────────────────────┐
│  1. CORS                                     │
│     allow_origins=*, allow_methods=*,        │
│     expose: x-trace-id, x-response-time-ms   │
├──────────────────────────────────────────────┤
│  2. Rate Limiter (Token Bucket)              │
│     • 10 req/s global                        │
│     • 60 req/min per IP                      │
│     • 300 req/min per user                   │
│     • 30 req/min per endpoint                │
├──────────────────────────────────────────────┤
│  3. Authentication                           │
│     • JWT Bearer token (HS256)               │
│     • API key (SHA256-hashed storage)        │
│     • Public paths: /health, /auth/*, /docs  │
├──────────────────────────────────────────────┤
│  4. Validation                               │
│     • Content-Type required for POST/PUT     │
│     • Max body size: 10MB                    │
│     • Host header required                   │
├──────────────────────────────────────────────┤
│  5. Error Handler                            │
│     • Catches all exceptions → 500 + trace_id│
│     • HTTPException → structured error       │
├──────────────────────────────────────────────┤
│  6. Response Headers                         │
│     x-trace-id, x-response-time-ms           │
└──────────────────────────────────────────────┘
```

---

## Files

| File | Purpose |
|------|---------|
| `gateway.py` | `OrchestraGateway` — stacked middleware handler |
| `server.py` | FastAPI app with all middleware + routes |
| `middleware/auth.py` | `JWTAuthMiddleware` + `APIKeyAuth` + `AuthMiddleware` |
| `middleware/rate_limiter.py` | `RateLimiter` + `TokenBucket` + `RateLimitRule` |
| `middleware/logging.py` | `LoggingMiddleware` + `TracingMiddleware` |
| `middleware/validation.py` | `ValidationMiddleware` — content-type, size, headers |

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | Public | Service health |
| POST | `/api/chat` | Required | Unified chat |
| POST | `/auth/token` | Public | Create JWT |
| POST | `/auth/api-key` | Public | Create API key |
| GET | `/admin/gateway/stats` | Required | Routes, limits, keys |
| GET | `/admin/gateway/routes` | Required | Registered route keys |

## Configuration

```python
gateway = OrchestraGateway(jwt_secret="your-secret")
app = create_app()  # FastAPI with all middleware
```

Environment: `JWT_SECRET`, `CORS_ORIGINS`, `GATEWAY_PORT`, `GATEWAY_HOST`

## Test Coverage (31 tests)

- Token bucket: consume, refill, capacity cap
- Rate limiter: per-IP isolation, global throttle, cleanup, add rule
- JWT: create, verify, expired, invalid, secret mismatch
- API key: create, verify, revoke, reject invalid
- Auth middleware: public bypass, JWT, API key, missing header
- FastAPI integration: health, auth, chat, CORS, admin
