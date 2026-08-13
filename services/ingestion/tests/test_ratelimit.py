"""Real-Redis tests for `app.core.ratelimit.TokenBucketLimiter` — the Lua
script's atomicity/refill math is exactly the kind of thing a mock can't
meaningfully verify; these run against an actual local Redis (skipped if
none is reachable, same convention as any other local-infra-dependent
test in this suite would use)."""

from __future__ import annotations

import asyncio

import pytest
from redis.asyncio import Redis

from app.core.ratelimit import TokenBucketLimiter

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def redis():
    client = Redis.from_url("redis://localhost:6379/15", decode_responses=True)
    try:
        await client.ping()
    except Exception:
        pytest.skip("no local Redis reachable on localhost:6379")
    yield client
    await client.flushdb()
    await client.aclose()


class TestTokenBucketLimiter:
    async def test_allows_requests_up_to_capacity(self, redis):
        limiter = TokenBucketLimiter(redis, capacity=3, window_seconds=60)

        results = [await limiter.check("caller-a") for _ in range(3)]

        assert all(r.allowed for r in results)

    async def test_blocks_once_capacity_is_exhausted(self, redis):
        limiter = TokenBucketLimiter(redis, capacity=3, window_seconds=60)
        for _ in range(3):
            await limiter.check("caller-b")

        result = await limiter.check("caller-b")

        assert result.allowed is False
        assert result.retry_after_seconds > 0

    async def test_different_keys_have_independent_buckets(self, redis):
        limiter = TokenBucketLimiter(redis, capacity=1, window_seconds=60)
        await limiter.check("caller-c")  # exhausts caller-c's single token

        result_c = await limiter.check("caller-c")
        result_d = await limiter.check("caller-d")

        assert result_c.allowed is False
        assert result_d.allowed is True

    async def test_refills_over_time(self, redis):
        # capacity=1, window=0.2s -> refill_rate=5 tokens/sec, so waiting
        # ~0.25s should refill the single token.
        limiter = TokenBucketLimiter(redis, capacity=1, window_seconds=0.2)
        first = await limiter.check("caller-e")
        immediately_after = await limiter.check("caller-e")

        await asyncio.sleep(0.3)
        after_refill = await limiter.check("caller-e")

        assert first.allowed is True
        assert immediately_after.allowed is False
        assert after_refill.allowed is True

    async def test_concurrent_requests_never_exceed_capacity(self, redis):
        """The atomicity claim, verified directly: fire more concurrent
        requests than the bucket's capacity and confirm exactly
        `capacity` of them succeed -- a non-atomic read-modify-write
        (GET, compute in Python, SET) would let more through."""
        limiter = TokenBucketLimiter(redis, capacity=5, window_seconds=60)

        results = await asyncio.gather(*[limiter.check("caller-f") for _ in range(20)])

        assert sum(1 for r in results if r.allowed) == 5
