"""Lua token-bucket script with SHA caching for Redis EVALSHA/EVAL."""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

# Atomic token-bucket: refill + consume in a single round-trip.
# KEYS[1] = bucket key
# ARGV = now_ms, capacity, refill_per_ms, cost, ttl_ms
# Returns {allowed (0|1), remaining_tokens, retry_after_ms}
TOKEN_BUCKET_SCRIPT = """\
local key = KEYS[1]
local now = tonumber(ARGV[1])
local capacity = tonumber(ARGV[2])
local refill_per_ms = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])
local ttl_ms = tonumber(ARGV[5])

local data = redis.call('HMGET', key, 'tokens', 'lastRefillMs')
local tokens = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
  tokens = capacity
  last_refill = now
end

-- Refill based on elapsed time
local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_per_ms)

local allowed = 0
local retry_after_ms = 0
if tokens >= cost then
  tokens = tokens - cost
  allowed = 1
else
  local deficit = cost - tokens
  if refill_per_ms > 0 then
    retry_after_ms = math.ceil(deficit / refill_per_ms)
  else
    retry_after_ms = -1
  end
end

redis.call('HMSET', key, 'tokens', tokens, 'lastRefillMs', now)
redis.call('PEXPIRE', key, ttl_ms)

return {allowed, tokens, retry_after_ms}
"""

# Per-connection SHA tracking — EVALSHA only works after SCRIPT LOAD on
# that specific Redis instance.
_loaded_connections: set[int] = set()


def _compute_sha() -> str:
    return hashlib.sha1(TOKEN_BUCKET_SCRIPT.encode()).hexdigest()


async def _ensure_loaded(redis: Redis) -> str:
    """Load the script into Redis if not yet done for this connection."""
    conn_id = id(redis)
    if conn_id not in _loaded_connections:
        sha = await redis.script_load(TOKEN_BUCKET_SCRIPT)
        _loaded_connections.add(conn_id)
        return sha
    return _compute_sha()


async def eval_token_bucket(
    redis: Redis,
    key: str,
    now_ms: int,
    capacity: int,
    refill_per_ms: float,
    cost: int = 1,
    ttl_ms: int = 120_000,
) -> tuple[bool, float, int]:
    """Run the token-bucket Lua script via EVALSHA, falling back to EVAL.

    Returns (allowed, remaining_tokens, retry_after_ms).
    """
    sha = await _ensure_loaded(redis)
    args = [now_ms, capacity, refill_per_ms, cost, ttl_ms]
    try:
        result = await redis.evalsha(sha, 1, key, *args)  # type: ignore[misc]
    except Exception as exc:
        exc_str = f"{type(exc).__name__}: {exc}"
        if "NOSCRIPT" in exc_str or "NoScript" in exc_str:
            result = await redis.eval(TOKEN_BUCKET_SCRIPT, 1, key, *args)  # type: ignore[misc]
        else:
            raise
    allowed = bool(int(result[0]))
    remaining = float(result[1])
    retry_after = int(result[2])
    return allowed, remaining, retry_after
