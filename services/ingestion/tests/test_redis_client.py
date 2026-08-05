import pytest

from app.core.config import get_settings
from app.db import redis as redis_client

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _reset_caches():
    get_settings.cache_clear()
    redis_client.get_redis.cache_clear()
    redis_client.get_breaker.cache_clear()
    yield
    get_settings.cache_clear()
    redis_client.get_redis.cache_clear()
    redis_client.get_breaker.cache_clear()


def test_get_redis_uses_settings_redis_url(monkeypatch):
    monkeypatch.setenv("REDIS_URL", "")  # else the real .env's REDIS_URL would win
    monkeypatch.setenv("REDIS_HOST", "cache.internal")
    monkeypatch.setenv("REDIS_PORT", "6380")
    monkeypatch.setenv("REDIS_DB", "3")

    redis = redis_client.get_redis()

    kwargs = redis.connection_pool.connection_kwargs
    assert kwargs["host"] == "cache.internal"
    assert kwargs["port"] == 6380
    assert kwargs["db"] == 3


def test_get_redis_is_cached():
    assert redis_client.get_redis() is redis_client.get_redis()


async def test_close_redis_is_safe_without_a_live_server():
    await redis_client.close_redis()


def test_get_breaker_returns_a_circuit_breaker_bound_to_get_redis():
    from app.service.pipeline.circuit_breaker import CircuitBreaker

    breaker = redis_client.get_breaker("bom")

    assert isinstance(breaker, CircuitBreaker)
    assert breaker.name == "bom"


def test_get_breaker_is_cached_per_name():
    assert redis_client.get_breaker("bom") is redis_client.get_breaker("bom")
    assert redis_client.get_breaker("bom") is not redis_client.get_breaker("aemo_nem")


def test_get_breaker_uses_default_threshold_and_timeout():
    breaker = redis_client.get_breaker("bom")

    assert breaker.failure_threshold == 5
    assert breaker.reset_timeout == 60.0


def test_get_breaker_uses_settings_overrides(monkeypatch):
    monkeypatch.setenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "10")
    monkeypatch.setenv("CIRCUIT_BREAKER_RESET_TIMEOUT", "900")

    breaker = redis_client.get_breaker("aemo_nem")

    assert breaker.failure_threshold == 10
    assert breaker.reset_timeout == 900.0
