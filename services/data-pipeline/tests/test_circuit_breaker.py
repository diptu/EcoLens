import asyncio

import pytest

from app.service.pipeline.circuit_breaker import (
    CLOSED,
    HALF_OPEN,
    OPEN,
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeRedis:
    """Minimal in-memory stand-in for the subset of redis.asyncio.Redis
    that CircuitBreaker uses — no live Redis needed for these tests."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value):
        self.store[key] = str(value)

    async def incr(self, key):
        self.store[key] = str(int(self.store.get(key, 0)) + 1)
        return int(self.store[key])

    async def delete(self, *keys):
        for k in keys:
            self.store.pop(k, None)


@pytest.fixture
def redis():
    return FakeRedis()


async def _fail():
    raise ValueError("boom")


async def _ok():
    return "ok"


async def test_starts_closed(redis):
    cb = CircuitBreaker("svc", redis)
    assert await cb.state == CLOSED


async def test_stays_closed_below_failure_threshold(redis):
    cb = CircuitBreaker("svc", redis, failure_threshold=3)
    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(_fail)
    assert await cb.state == CLOSED


async def test_opens_at_failure_threshold(redis):
    cb = CircuitBreaker("svc", redis, failure_threshold=2)
    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(_fail)
    assert await cb.state == OPEN


async def test_open_breaker_rejects_calls_without_invoking_fn(redis):
    cb = CircuitBreaker("svc", redis, failure_threshold=1, reset_timeout=999)
    with pytest.raises(ValueError):
        await cb.call(_fail)
    assert await cb.state == OPEN

    calls = []

    async def tracked():
        calls.append(1)
        return "ok"

    with pytest.raises(CircuitOpenError):
        await cb.call(tracked)
    assert calls == []


async def test_transitions_to_half_open_after_reset_timeout(redis):
    cb = CircuitBreaker("svc", redis, failure_threshold=1, reset_timeout=0)
    with pytest.raises(ValueError):
        await cb.call(_fail)
    assert await cb.state == HALF_OPEN


async def test_successful_half_open_trial_closes_the_breaker(redis):
    cb = CircuitBreaker("svc", redis, failure_threshold=1, reset_timeout=0)
    with pytest.raises(ValueError):
        await cb.call(_fail)
    assert await cb.state == HALF_OPEN

    result = await cb.call(_ok)

    assert result == "ok"
    assert await cb.state == CLOSED


async def test_failed_half_open_trial_reopens_the_breaker(redis):
    cb = CircuitBreaker("svc", redis, failure_threshold=1, reset_timeout=0.2)
    with pytest.raises(ValueError):
        await cb.call(_fail)
    await asyncio.sleep(0.25)
    assert await cb.state == HALF_OPEN

    with pytest.raises(ValueError):
        await cb.call(_fail)

    # opened_at was just reset, so we're immediately back inside the
    # reset_timeout window -> open, not half_open again.
    assert await cb.state == OPEN


async def test_state_value_is_the_plain_string():
    # CircuitState is a str-Enum, so `.value` gives back the raw string
    # (this is exactly how app.service.pipeline.tasks._common consumes it).
    assert CircuitState.OPEN.value == "open"
    assert CircuitState.CLOSED.value == "closed"
    assert CircuitState.HALF_OPEN.value == "half_open"


async def test_call_forwards_positional_and_keyword_args(redis):
    cb = CircuitBreaker("svc", redis)
    seen = {}

    async def fetch(region, *, lookback_minutes):
        seen["region"] = region
        seen["lookback_minutes"] = lookback_minutes
        return "ok"

    result = await cb.call(fetch, "NSW1", lookback_minutes=30)

    assert result == "ok"
    assert seen == {"region": "NSW1", "lookback_minutes": 30}
