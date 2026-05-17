# Rate-Limit Middleware

Per-tenant token-bucket rate limiting for Horizon Orchestra with Redis primary and in-memory fallback.

## Architecture

```
Request → RateLimitMiddleware.before(ctx)
              │
              ├─ CircuitBreaker.allow_request()?
              │     ├─ YES → Redis Lua token-bucket (EVALSHA)
              │     │         ├─ success → record_success(), return decision
              │     │         └─ failure → record_failure(), fall through
              │     └─ NO  → skip Redis
              │
              └─ LocalTokenBucket.consume() (in-memory fallback)
                    └─ return decision
```

### Components

| Module | Purpose |
|--------|---------|
| `rate_limit.py` | Main middleware — `OrchestraMiddleware` protocol, `RateLimitMiddleware` class |
| `_lua.py` | Lua token-bucket script, SHA caching, EVALSHA/EVAL fallback |
| `_bucket.py` | asyncio-safe in-memory token bucket (fail-open fallback) |
| `_breaker.py` | Circuit breaker: CLOSED → OPEN → HALF_OPEN → CLOSED |

### Middleware Protocol

```python
class OrchestraMiddleware(Protocol):
    async def before(self, ctx: dict) -> dict | None:  # None = block
    async def after(self, ctx: dict, result: Any) -> Any:
    async def on_error(self, ctx: dict, error: Exception) -> Any:
```

## Failure Modes

1. **Redis down** — circuit breaker opens after N consecutive failures (default 5). Middleware switches to in-memory limiter. Requests are *allowed* (fail-open) but rate-limited per-process only.
2. **Redis slow** — same as down if timeouts cause exceptions.
3. **Breaker recovery** — after cooldown (default 30s), one probe request is sent. On success, breaker closes and Redis resumes.
4. **No Redis configured** — middleware uses in-memory limiter from the start.
5. **Disabled** — set `RATE_LIMIT_ENABLED=false` to bypass entirely.

## Tenant Configuration

```python
opts = RateLimitOptions(
    tenant_id="tenant-123",
    capacity=60,              # max burst
    refill_per_second=10.0,   # sustained rate
    redis_key_prefix="rl:orchestra",
    cost=1,                   # tokens per request
)
```

## Audit Events

The middleware emits events via an `AuditSink` protocol:

- `rate_limit.allowed` — request permitted
- `rate_limit.throttled` — request blocked
- `rate_limit.breaker_opened` — circuit breaker tripped
- `rate_limit.breaker_closed` — circuit breaker recovered

Provide a custom `AuditSink` (e.g., wired to AuditLedger) or use `LoggingAuditSink` for development.

## Tuning Guide

| Parameter | Default | Notes |
|-----------|---------|-------|
| `capacity` | 60 | Peak burst size. Set per-tier: Free=20, Pro=60, Max=200 |
| `refill_per_second` | 10.0 | Sustained throughput. 10 req/s = 600 req/min |
| `failure_threshold` | 5 | Breaker trips after this many consecutive Redis failures |
| `cooldown_seconds` | 30.0 | Time before breaker allows a probe request |
| `RATE_LIMIT_ENABLED` | `true` | Env var to disable middleware entirely |

## Integration

```python
from orchestra.middleware import RateLimitMiddleware, LoggingAuditSink

mw = await RateLimitMiddleware.create(
    redis_url="redis://localhost:6379",
    audit_sink=LoggingAuditSink(),
)

# In middleware chain: after BeyondGuardrails, before PolicyEngine
# TODO: Wire into orchestra/router.py middleware chain
```
