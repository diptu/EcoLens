"""Redis-backed token-bucket rate limiting (`README.md`: "Redis token
bucket, default 60 req/min per token"; `TODO.md`'s IAM section item 6 —
"not implemented on any endpoint yet").

A real token bucket (continuous refill, not a fixed window that resets
all at once) implemented as a single atomic Redis Lua script — read-
modify-write done any other way (`GET`, compute in Python, `SET`) would
race under concurrent requests from the same caller, letting more
through than the configured limit. `EVAL` runs the whole check-and-
consume as one atomic operation on the Redis server, so that race can't
happen regardless of how many requests arrive at the same instant.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from redis.asyncio import Redis

# KEYS[1] = bucket key
# ARGV[1] = capacity (max tokens the bucket can hold)
# ARGV[2] = refill_rate (tokens added per second)
# ARGV[3] = now (unix seconds, float)
# ARGV[4] = requested tokens (always 1 here -- one request costs one token)
#
# Stored as a Redis hash {tokens, ts} so both the current token count and
# the timestamp they were last computed at travel together atomically.
# A bucket that's never been touched starts full (a fresh caller isn't
# penalised for buckets it's never used before).
_TOKEN_BUCKET_SCRIPT = (  # nosec B105 -- false positive: bandit's hardcoded-password heuristic matches on "TOKEN" in the variable name; this is a Lua script constant, not a credential
    """
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])

local bucket = redis.call("HMGET", KEYS[1], "tokens", "ts")
local tokens = tonumber(bucket[1])
local last_ts = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_ts = now
end

local elapsed = math.max(0, now - last_ts)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
end

redis.call("HMSET", KEYS[1], "tokens", tostring(tokens), "ts", tostring(now))
-- A bucket idle for 2x the time it'd take to refill from empty is safe
-- to expire -- keeps Redis from accumulating one hash per caller forever.
redis.call("EXPIRE", KEYS[1], math.ceil((capacity / refill_rate) * 2))

return {allowed, tostring(tokens)}
"""
)


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: float
    limit: int
    retry_after_seconds: float


class TokenBucketLimiter:
    def __init__(
        self, redis: Redis, *, capacity: int, window_seconds: float = 60.0
    ) -> None:
        self.redis = redis
        self.capacity = capacity
        self.refill_rate = capacity / window_seconds

    async def check(self, key: str) -> RateLimitResult:
        """Consumes one token from `key`'s bucket if available. Always
        atomic (single Lua `EVAL`) regardless of concurrent callers
        sharing the same key."""
        now = time.time()
        allowed_raw, remaining_raw = await self.redis.eval(  # type: ignore[misc]
            _TOKEN_BUCKET_SCRIPT,
            1,
            f"ratelimit:{key}",
            self.capacity,
            self.refill_rate,
            now,
            1,
        )
        allowed = bool(int(allowed_raw))
        remaining = float(remaining_raw)
        retry_after = 0.0 if allowed else max(0.0, (1 - remaining) / self.refill_rate)
        return RateLimitResult(
            allowed=allowed,
            remaining=remaining,
            limit=self.capacity,
            retry_after_seconds=retry_after,
        )
