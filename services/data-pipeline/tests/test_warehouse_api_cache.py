"""Tests for ecolens.warehouse.api.cache.Cache.

Uses a fake redis-shaped client so these never touch a real Redis
server.
"""

from __future__ import annotations

from typing import Any

import pytest

from ecolens.warehouse.api.cache import Cache
from ecolens.warehouse.api.settings import WarehouseApiSettings


class _FakeRedisClient:
    def __init__(self, *, ping_raises: Exception | None = None) -> None:
        self._store: dict[str, str] = {}
        self._ping_raises = ping_raises
        self.closed = False

    async def ping(self) -> None:
        if self._ping_raises:
            raise self._ping_raises

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def aclose(self) -> None:
        self.closed = True


class TestDisabled:
    def test_disabled_without_redis_url(self):
        cache = Cache(WarehouseApiSettings())
        assert cache.enabled is False

    @pytest.mark.asyncio
    async def test_connect_is_noop_when_disabled(self):
        cache = Cache(WarehouseApiSettings())
        await cache.connect()
        assert cache.connected is False

    @pytest.mark.asyncio
    async def test_get_returns_none_when_disabled(self):
        cache = Cache(WarehouseApiSettings())
        assert await cache.get("k") is None

    @pytest.mark.asyncio
    async def test_set_does_not_raise_when_disabled(self):
        cache = Cache(WarehouseApiSettings())
        await cache.set("k", {"a": 1})  # should not raise


class TestEnabled:
    def test_enabled_with_redis_url(self):
        cache = Cache(WarehouseApiSettings(redis_url="redis://localhost:6379/0"))
        assert cache.enabled is True

    @pytest.mark.asyncio
    async def test_connect_failure_disables_cache(self, monkeypatch):
        import ecolens.warehouse.api.cache as cache_module

        monkeypatch.setattr(
            cache_module.aioredis,
            "from_url",
            lambda *a, **kw: _FakeRedisClient(ping_raises=ConnectionError("down")),
        )
        cache = Cache(WarehouseApiSettings(redis_url="redis://localhost:6379/0"))
        await cache.connect()
        assert cache.enabled is False
        assert cache.connected is False

    @pytest.mark.asyncio
    async def test_get_set_round_trip(self, monkeypatch):
        import ecolens.warehouse.api.cache as cache_module

        fake_client = _FakeRedisClient()
        monkeypatch.setattr(
            cache_module.aioredis, "from_url", lambda *a, **kw: fake_client
        )
        cache = Cache(WarehouseApiSettings(redis_url="redis://localhost:6379/0"))
        await cache.connect()
        assert cache.connected is True

        await cache.set("demand:NSW1", {"demand_mw": 5000.0})
        result: Any = await cache.get("demand:NSW1")
        assert result == {"demand_mw": 5000.0}

    @pytest.mark.asyncio
    async def test_get_missing_key_returns_none(self, monkeypatch):
        import ecolens.warehouse.api.cache as cache_module

        fake_client = _FakeRedisClient()
        monkeypatch.setattr(
            cache_module.aioredis, "from_url", lambda *a, **kw: fake_client
        )
        cache = Cache(WarehouseApiSettings(redis_url="redis://localhost:6379/0"))
        await cache.connect()
        assert await cache.get("nope") is None

    @pytest.mark.asyncio
    async def test_disconnect_closes_client(self, monkeypatch):
        import ecolens.warehouse.api.cache as cache_module

        fake_client = _FakeRedisClient()
        monkeypatch.setattr(
            cache_module.aioredis, "from_url", lambda *a, **kw: fake_client
        )
        cache = Cache(WarehouseApiSettings(redis_url="redis://localhost:6379/0"))
        await cache.connect()
        await cache.disconnect()
        assert fake_client.closed is True
        assert cache.connected is False
