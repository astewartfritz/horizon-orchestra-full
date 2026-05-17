"""Rate-limit middleware for Horizon Orchestra.

Provides per-tenant token-bucket rate limiting backed by Redis (primary)
with an in-memory fallback when Redis is unavailable, governed by a
circuit breaker.

Usage::

    from orchestra.middleware import RateLimitMiddleware, RateLimitOptions

    middleware = await RateLimitMiddleware.create(redis_url="redis://localhost:6379")
    decision = await middleware.check(RateLimitOptions(tenant_id="t-123"))
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ._breaker import BreakerState, CircuitBreaker
from ._bucket import LocalTokenBucket

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

def _is_rate_limit_enabled() -> bool:
    return os.environ.get("RATE_LIMIT_ENABLED", "true").lower() in (
        "true",
        "1",
        "yes",
    )


RATE_LIMIT_ENABLED = _is_rate_limit_enabled()  # snapshot for fast import-time check


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    remaining: float
    retry_after_ms: int
    source: str  # "redis" | "memory" | "disabled"


@dataclass
class RateLimitOptions:
    tenant_id: str
    capacity: int = 60
    refill_per_second: float = 10.0
    redis_key_prefix: str = "rl:orchestra"
    clock_skew_ms: int = 0
    cost: int = 1


# ---------------------------------------------------------------------------
# Middleware protocol — matches spec's before/after/on_error hooks
# ---------------------------------------------------------------------------

@runtime_checkable
class OrchestraMiddleware(Protocol):
    """Async middleware protocol for the Orchestra request pipeline."""

    async def before(self, ctx: dict[str, Any]) -> dict[str, Any] | None:
        """Called before processing. Return modified ctx or None to block."""
        ...

    async def after(self, ctx: dict[str, Any], result: Any) -> Any:
        """Called after processing. May transform the result."""
        ...

    async def on_error(self, ctx: dict[str, Any], error: Exception) -> Any:
        """Called when processing raises. May recover or re-raise."""
        ...


# ---------------------------------------------------------------------------
# Audit sink (pluggable — wire to AuditLedger when available)
# ---------------------------------------------------------------------------

@runtime_checkable
class AuditSink(Protocol):
    """Async event sink for rate-limit audit events.

    TODO: Wire to the real AuditLedger once BeyondGuardrails/PolicyEngine
    integration is complete. For now, callers can provide any object with
    an ``emit(event_type, payload)`` async method.
    """

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None: ...


class _NullAuditSink:
    """Default no-op sink."""

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        pass


class LoggingAuditSink:
    """Audit sink that logs events — useful for development/testing."""

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        logger.info("audit: %s %s", event_type, payload)


# ---------------------------------------------------------------------------
# Main middleware
# ---------------------------------------------------------------------------

class RateLimitMiddleware:
    """Rate-limit middleware with Redis primary + in-memory fallback.

    Implements :class:`OrchestraMiddleware`.
    """

    def __init__(
        self,
        redis: Any | None = None,
        *,
        breaker: CircuitBreaker | None = None,
        fallback: LocalTokenBucket | None = None,
        audit_sink: AuditSink | None = None,
        default_capacity: int = 60,
        default_refill_per_second: float = 10.0,
    ) -> None:
        self._redis = redis
        self._breaker = breaker or CircuitBreaker()
        self._fallback = fallback or LocalTokenBucket(
            capacity=default_capacity,
            refill_per_second=default_refill_per_second,
        )
        self._audit: AuditSink = audit_sink or _NullAuditSink()
        self._default_capacity = default_capacity
        self._default_refill = default_refill_per_second

    # -- Factory ----------------------------------------------------------

    @classmethod
    async def create(
        cls,
        redis_url: str = "redis://localhost:6379",
        **kwargs: Any,
    ) -> RateLimitMiddleware:
        """Create middleware with an async Redis connection."""
        try:
            from redis.asyncio import from_url

            redis = from_url(redis_url, decode_responses=False)
            await redis.ping()  # type: ignore[misc]
        except Exception:
            logger.warning("Redis unavailable at %s — running memory-only", redis_url)
            redis = None
        return cls(redis=redis, **kwargs)

    # -- Core check -------------------------------------------------------

    async def check(self, opts: RateLimitOptions | None = None) -> RateLimitDecision:
        """Evaluate the rate limit for the given options."""
        if not _is_rate_limit_enabled():
            return RateLimitDecision(
                allowed=True, remaining=-1, retry_after_ms=0, source="disabled"
            )

        if opts is None:
            opts = RateLimitOptions(tenant_id="__default__")

        decision = await self._try_redis(opts)
        if decision is not None:
            await self._emit_events(decision, opts)
            return decision

        # Fallback to in-memory
        allowed, remaining, retry_after = await self._fallback.consume(
            opts.tenant_id, opts.cost
        )
        decision = RateLimitDecision(
            allowed=allowed,
            remaining=remaining,
            retry_after_ms=retry_after,
            source="memory",
        )
        await self._emit_events(decision, opts)
        return decision

    async def _try_redis(self, opts: RateLimitOptions) -> RateLimitDecision | None:
        if self._redis is None:
            return None
        if not self._breaker.allow_request():
            return None

        try:
            from ._lua import eval_token_bucket

            now_ms = int(time.time() * 1000) + opts.clock_skew_ms
            refill_per_ms = opts.refill_per_second / 1000.0
            ttl_ms = int((opts.capacity / max(opts.refill_per_second, 0.001)) * 1000) + 60_000
            key = f"{opts.redis_key_prefix}:{opts.tenant_id}"

            allowed, remaining, retry_after = await eval_token_bucket(
                self._redis,
                key=key,
                now_ms=now_ms,
                capacity=opts.capacity,
                refill_per_ms=refill_per_ms,
                cost=opts.cost,
                ttl_ms=ttl_ms,
            )
            self._breaker.record_success()
            return RateLimitDecision(
                allowed=allowed,
                remaining=remaining,
                retry_after_ms=retry_after,
                source="redis",
            )
        except Exception:
            logger.warning("Redis call failed, recording breaker failure", exc_info=True)
            self._breaker.record_failure()
            await self._check_breaker_events(opts)
            return None

    # -- Audit events -----------------------------------------------------

    async def _emit_events(self, decision: RateLimitDecision, opts: RateLimitOptions) -> None:
        event_type = "rate_limit.allowed" if decision.allowed else "rate_limit.throttled"
        await self._audit.emit(
            event_type,
            {
                "tenant_id": opts.tenant_id,
                "remaining": decision.remaining,
                "source": decision.source,
                "retry_after_ms": decision.retry_after_ms,
            },
        )

    async def _check_breaker_events(self, opts: RateLimitOptions) -> None:
        state = self._breaker.state
        if state is BreakerState.OPEN:
            await self._audit.emit(
                "rate_limit.breaker_opened",
                {"tenant_id": opts.tenant_id},
            )

    # -- OrchestraMiddleware protocol -------------------------------------

    async def before(self, ctx: dict[str, Any]) -> dict[str, Any] | None:
        """Rate-limit check before request processing.

        Injects ``rate_limit_decision`` into ctx. Returns None (blocks)
        if the request is throttled.
        """
        tenant_id = ctx.get("tenant_id", "__default__")
        opts = RateLimitOptions(
            tenant_id=tenant_id,
            capacity=ctx.get("rate_limit_capacity", self._default_capacity),
            refill_per_second=ctx.get("rate_limit_refill", self._default_refill),
        )
        decision = await self.check(opts)
        ctx["rate_limit_decision"] = decision
        if not decision.allowed:
            return None  # blocked
        return ctx

    async def after(self, ctx: dict[str, Any], result: Any) -> Any:
        """Pass-through after hook."""
        return result

    async def on_error(self, ctx: dict[str, Any], error: Exception) -> Any:
        """Pass-through error hook — rate limiting doesn't alter error handling."""
        raise error

    # -- Cleanup ----------------------------------------------------------

    async def close(self) -> None:
        """Close the Redis connection if we own it."""
        if self._redis is not None:
            try:
                await self._redis.aclose()
            except Exception:
                pass
