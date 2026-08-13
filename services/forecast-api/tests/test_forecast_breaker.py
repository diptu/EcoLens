import pytest

from app.service.ml.forecast_breaker import (
    CLOSED,
    HALF_OPEN,
    OPEN,
    ForecastCircuitBreaker,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeRedis:
    """Minimal in-memory stand-in for the subset of redis.asyncio.Redis
    ForecastCircuitBreaker uses -- no live Redis needed for these tests,
    matching data-pipeline's identical `FakeRedis` test double."""

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


async def test_starts_closed(redis):
    cb = ForecastCircuitBreaker("lstm_demand:NSW1", redis)

    assert await cb.state == CLOSED


async def test_stays_closed_below_failure_threshold(redis):
    cb = ForecastCircuitBreaker("lstm_demand:NSW1", redis, failure_threshold=3)

    await cb.record_failure()
    await cb.record_failure()

    assert await cb.state == CLOSED


async def test_opens_at_failure_threshold(redis):
    cb = ForecastCircuitBreaker("lstm_demand:NSW1", redis, failure_threshold=2)

    await cb.record_failure()
    await cb.record_failure()

    assert await cb.state == OPEN


async def test_a_success_resets_the_failure_count(redis):
    cb = ForecastCircuitBreaker("lstm_demand:NSW1", redis, failure_threshold=3)

    await cb.record_failure()
    await cb.record_failure()
    await cb.record_success()
    await cb.record_failure()
    await cb.record_failure()

    # Two failures again post-reset -- still below threshold=3.
    assert await cb.state == CLOSED


async def test_transitions_to_half_open_after_reset_timeout(redis, monkeypatch):
    cb = ForecastCircuitBreaker(
        "lstm_demand:NSW1", redis, failure_threshold=1, reset_timeout=0.01
    )
    await cb.record_failure()
    assert await cb.state == OPEN

    import time as time_module

    real_now = time_module.time()
    monkeypatch.setattr(
        "app.service.ml.forecast_breaker.time.time", lambda: real_now + 10
    )

    assert await cb.state == HALF_OPEN


async def test_half_open_success_closes_the_breaker(redis, monkeypatch):
    cb = ForecastCircuitBreaker(
        "lstm_demand:NSW1", redis, failure_threshold=1, reset_timeout=0.01
    )
    await cb.record_failure()

    import time as time_module

    real_now = time_module.time()
    monkeypatch.setattr(
        "app.service.ml.forecast_breaker.time.time", lambda: real_now + 10
    )
    assert await cb.state == HALF_OPEN

    await cb.record_success()

    assert await cb.state == CLOSED


async def test_half_open_failure_reopens_immediately(redis, monkeypatch):
    cb = ForecastCircuitBreaker(
        "lstm_demand:NSW1", redis, failure_threshold=1, reset_timeout=0.01
    )
    await cb.record_failure()

    import time as time_module

    real_now = time_module.time()
    monkeypatch.setattr(
        "app.service.ml.forecast_breaker.time.time", lambda: real_now + 10
    )
    assert await cb.state == HALF_OPEN

    # A single failure during the half-open trial re-opens immediately --
    # no "give it a few more tries" even though `failure_threshold=1`
    # would otherwise suggest it's the same bar as the original trip.
    await cb.record_failure()

    assert await cb.state == OPEN


async def test_breakers_are_independent_per_name(redis):
    nsw = ForecastCircuitBreaker("lstm_demand:NSW1", redis, failure_threshold=1)
    qld = ForecastCircuitBreaker("lstm_demand:QLD1", redis, failure_threshold=1)

    await nsw.record_failure()

    assert await nsw.state == OPEN
    assert await qld.state == CLOSED
