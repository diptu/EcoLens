"""Tests for ecolens.ingestion.core.data_sources_cache.

`get_redis_client` is monkeypatched to a small in-memory fake -- no
real Redis server touched.
"""

from __future__ import annotations

import fnmatch

import pytest

import ecolens.ingestion.core.data_sources_cache as cache_module


class _FakeRedis:
    def __init__(self, *, raise_on_connect: bool = False) -> None:
        self._store: dict[str, str] = {}
        self._raise_on_connect = raise_on_connect

    def _maybe_raise(self) -> None:
        if self._raise_on_connect:
            raise ConnectionError("redis unreachable")

    async def get(self, key: str) -> str | None:
        self._maybe_raise()
        return self._store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._maybe_raise()
        self._store[key] = value

    async def delete(self, *keys: str) -> int:
        self._maybe_raise()
        n = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                n += 1
        return n

    async def scan(self, cursor: int, match: str, count: int) -> tuple[int, list[str]]:
        self._maybe_raise()
        matched = [k for k in self._store if fnmatch.fnmatch(k, match)]
        return 0, matched


class TestCacheKeys:
    def test_one_cache_key_is_scoped_per_source(self):
        assert cache_module.one_cache_key("aemo_nem") == "datasources:one:v1:aemo_nem"
        assert cache_module.one_cache_key("bom") != cache_module.one_cache_key(
            "aemo_nem"
        )

    def test_list_cache_key_is_deterministic(self):
        query = {"category": "grid", "limit": 50}
        assert cache_module.list_cache_key(query) == cache_module.list_cache_key(query)

    def test_list_cache_key_ignores_param_order(self):
        a = cache_module.list_cache_key({"category": "grid", "limit": 50})
        b = cache_module.list_cache_key({"limit": 50, "category": "grid"})
        assert a == b

    def test_list_cache_key_differs_for_different_filters(self):
        a = cache_module.list_cache_key({"category": "grid"})
        b = cache_module.list_cache_key({"category": "weather"})
        assert a != b


class TestGetSetCache:
    @pytest.mark.asyncio
    async def test_round_trip(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
        await cache_module.set_cached("k", {"a": 1})
        assert await cache_module.get_cached("k") == {"a": 1}

    @pytest.mark.asyncio
    async def test_missing_key_returns_none(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
        assert await cache_module.get_cached("nope") is None

    @pytest.mark.asyncio
    async def test_get_degrades_to_none_when_redis_unavailable(self, monkeypatch):
        fake = _FakeRedis(raise_on_connect=True)
        monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
        assert await cache_module.get_cached("k") is None

    @pytest.mark.asyncio
    async def test_set_does_not_raise_when_redis_unavailable(self, monkeypatch):
        fake = _FakeRedis(raise_on_connect=True)
        monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
        await cache_module.set_cached("k", {"a": 1})  # should not raise


class TestInvalidation:
    @pytest.mark.asyncio
    async def test_invalidate_list_cache_clears_only_list_keys(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
        await cache_module.set_cached(cache_module.list_cache_key({"a": 1}), {"x": 1})
        await cache_module.set_cached(cache_module.one_cache_key("aemo_nem"), {"y": 1})

        await cache_module.invalidate_list_cache()

        assert (
            await cache_module.get_cached(cache_module.list_cache_key({"a": 1})) is None
        )
        assert await cache_module.get_cached(
            cache_module.one_cache_key("aemo_nem")
        ) == {"y": 1}

    @pytest.mark.asyncio
    async def test_invalidate_one_cache_clears_just_that_source(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
        await cache_module.set_cached(cache_module.one_cache_key("aemo_nem"), {"x": 1})
        await cache_module.set_cached(cache_module.one_cache_key("bom"), {"y": 1})

        await cache_module.invalidate_one_cache("aemo_nem")

        assert (
            await cache_module.get_cached(cache_module.one_cache_key("aemo_nem"))
            is None
        )
        assert await cache_module.get_cached(cache_module.one_cache_key("bom")) == {
            "y": 1
        }

    @pytest.mark.asyncio
    async def test_invalidate_does_not_raise_when_redis_unavailable(self, monkeypatch):
        fake = _FakeRedis(raise_on_connect=True)
        monkeypatch.setattr(cache_module, "get_redis_client", lambda: fake)
        await cache_module.invalidate_list_cache()  # should not raise
        await cache_module.invalidate_one_cache("aemo_nem")  # should not raise
