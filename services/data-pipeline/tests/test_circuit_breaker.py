"""Tests for ecolens.ingestion.circuit_breaker."""

from __future__ import annotations

import pytest

from conftest import FakeRedis

from ecolens.ingestion.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerOpen,
    retry_with_backoff,
)
from ecolens.ingestion.storage.settings import MongoSettings


async def _no_sleep(*_args: object, **_kwargs: object) -> None:
    return None


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_first_try_no_retry(self):
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            return "ok"

        result = await retry_with_backoff(fn, max_retries=3, backoff_base=1.5)
        assert result == "ok"
        assert calls == 1

    @pytest.mark.asyncio
    async def test_max_retries_zero_tries_once_and_propagates(self):
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            raise ConnectionError("down")

        with pytest.raises(ConnectionError, match="down"):
            await retry_with_backoff(fn, max_retries=0, backoff_base=1.5)
        assert calls == 1

    @pytest.mark.asyncio
    async def test_succeeds_after_transient_failures(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        calls = 0

        async def fn():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ConnectionError("down")
            return "ok"

        result = await retry_with_backoff(fn, max_retries=5, backoff_base=1.5)
        assert result == "ok"
        assert calls == 3

    @pytest.mark.asyncio
    async def test_raises_last_exception_after_exhausting_retries(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)

        async def fn():
            raise ConnectionError("still down")

        with pytest.raises(ConnectionError, match="still down"):
            await retry_with_backoff(fn, max_retries=3, backoff_base=1.5)

    @pytest.mark.asyncio
    async def test_on_retry_callback_invoked_per_attempt(self, monkeypatch):
        monkeypatch.setattr("asyncio.sleep", _no_sleep)
        attempts_seen: list[int] = []

        async def fn():
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            await retry_with_backoff(
                fn,
                max_retries=3,
                backoff_base=1.5,
                on_retry=lambda attempt, exc, delay: attempts_seen.append(attempt),
            )
        # 3 max_retries -> 2 retry callbacks (not called after the final attempt)
        assert attempts_seen == [1, 2]


@pytest.fixture
def settings() -> MongoSettings:
    return MongoSettings(
        ingest_circuit_breaker_threshold=3, ingest_circuit_breaker_timeout_seconds=60
    )


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_by_default(self, settings: MongoSettings):
        breaker = CircuitBreaker("test_source", FakeRedis(), settings=settings)
        await breaker.before_call()  # no raise

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self, settings: MongoSettings):
        breaker = CircuitBreaker("test_source", FakeRedis(), settings=settings)
        for _ in range(settings.ingest_circuit_breaker_threshold):
            await breaker.record_failure()
        with pytest.raises(CircuitBreakerOpen):
            await breaker.before_call()

    @pytest.mark.asyncio
    async def test_stays_closed_below_threshold(self, settings: MongoSettings):
        breaker = CircuitBreaker("test_source", FakeRedis(), settings=settings)
        for _ in range(settings.ingest_circuit_breaker_threshold - 1):
            await breaker.record_failure()
        await breaker.before_call()  # no raise

    @pytest.mark.asyncio
    async def test_success_resets_failure_count(self, settings: MongoSettings):
        breaker = CircuitBreaker("test_source", FakeRedis(), settings=settings)
        await breaker.record_failure()
        await breaker.record_failure()
        await breaker.record_success()
        await breaker.record_failure()
        await breaker.before_call()  # only 1 failure since reset, still closed

    @pytest.mark.asyncio
    async def test_half_open_after_timeout_elapses(
        self, settings: MongoSettings, monkeypatch
    ):
        redis = FakeRedis()
        breaker = CircuitBreaker("test_source", redis, settings=settings)
        for _ in range(settings.ingest_circuit_breaker_threshold):
            await breaker.record_failure()
        with pytest.raises(CircuitBreakerOpen):
            await breaker.before_call()

        # Simulate time passing beyond the timeout window.
        import time as time_module

        real_time = time_module.time
        monkeypatch.setattr(
            "ecolens.ingestion.circuit_breaker.time.time",
            lambda: real_time() + settings.ingest_circuit_breaker_timeout_seconds + 1,
        )
        await breaker.before_call()  # half-open: no raise

    @pytest.mark.asyncio
    async def test_call_records_success(self, settings: MongoSettings):
        breaker = CircuitBreaker("test_source", FakeRedis(), settings=settings)
        await breaker.record_failure()

        async def fn():
            return "ok"

        result = await breaker.call(fn)
        assert result == "ok"
        await breaker.before_call()  # failure count was reset by the success

    @pytest.mark.asyncio
    async def test_call_records_failure_and_reraises(self, settings: MongoSettings):
        breaker = CircuitBreaker("test_source", FakeRedis(), settings=settings)

        async def fn():
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await breaker.call(fn)

    @pytest.mark.asyncio
    async def test_call_raises_circuit_breaker_open_without_calling_fn(
        self, settings: MongoSettings
    ):
        breaker = CircuitBreaker("test_source", FakeRedis(), settings=settings)
        for _ in range(settings.ingest_circuit_breaker_threshold):
            await breaker.record_failure()

        called = False

        async def fn():
            nonlocal called
            called = True
            return "ok"

        with pytest.raises(CircuitBreakerOpen):
            await breaker.call(fn)
        assert called is False
