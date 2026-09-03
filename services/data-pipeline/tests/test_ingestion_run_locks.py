"""Tests for ecolens.ingestion.core.run_locks.

`get_redis_client` is monkeypatched to a small in-memory fake -- no
real Redis server touched.
"""

from __future__ import annotations

import pytest

import ecolens.ingestion.core.run_locks as locks_module


class _FakeRedis:
    def __init__(self, *, raise_on_connect: bool = False) -> None:
        self._store: dict[str, str] = {}
        self._raise_on_connect = raise_on_connect

    def _maybe_raise(self) -> None:
        if self._raise_on_connect:
            raise ConnectionError("redis unreachable")

    async def set(
        self, key: str, value: str, nx: bool = False, ex: int | None = None
    ) -> bool:
        self._maybe_raise()
        if nx and key in self._store:
            return False
        self._store[key] = value
        return True

    async def get(self, key: str) -> str | None:
        self._maybe_raise()
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        self._maybe_raise()
        n = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                n += 1
        return n


class TestRunLock:
    @pytest.mark.asyncio
    async def test_first_acquire_succeeds(self, monkeypatch):
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: _FakeRedis())
        assert await locks_module.acquire_run_lock("aemo_nem") is True

    @pytest.mark.asyncio
    async def test_second_acquire_fails_while_held(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        assert await locks_module.acquire_run_lock("aemo_nem") is True
        assert await locks_module.acquire_run_lock("aemo_nem") is False

    @pytest.mark.asyncio
    async def test_acquire_succeeds_again_after_release(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        await locks_module.acquire_run_lock("aemo_nem")
        await locks_module.release_run_lock("aemo_nem")
        assert await locks_module.acquire_run_lock("aemo_nem") is True

    @pytest.mark.asyncio
    async def test_locks_are_independent_per_source(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        assert await locks_module.acquire_run_lock("aemo_nem") is True
        assert await locks_module.acquire_run_lock("bom") is True

    @pytest.mark.asyncio
    async def test_degrades_to_allow_when_redis_unavailable(self, monkeypatch):
        fake = _FakeRedis(raise_on_connect=True)
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        assert await locks_module.acquire_run_lock("aemo_nem") is True
        assert await locks_module.acquire_run_lock("aemo_nem") is True  # still "allow"

    @pytest.mark.asyncio
    async def test_release_does_not_raise_when_redis_unavailable(self, monkeypatch):
        fake = _FakeRedis(raise_on_connect=True)
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        await locks_module.release_run_lock("aemo_nem")  # should not raise


class TestBackfillLock:
    @pytest.mark.asyncio
    async def test_independent_from_run_lock(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        assert await locks_module.acquire_run_lock("aemo_nem") is True
        assert await locks_module.acquire_backfill_lock("aemo_nem") is True

    @pytest.mark.asyncio
    async def test_second_acquire_fails_while_held(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        assert await locks_module.acquire_backfill_lock("aemo_nem") is True
        assert await locks_module.acquire_backfill_lock("aemo_nem") is False

    @pytest.mark.asyncio
    async def test_acquire_succeeds_again_after_release(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        await locks_module.acquire_backfill_lock("aemo_nem")
        await locks_module.release_backfill_lock("aemo_nem")
        assert await locks_module.acquire_backfill_lock("aemo_nem") is True


class TestIdempotency:
    @pytest.mark.asyncio
    async def test_round_trip(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        await locks_module.store_idempotent_response("key-1", {"a": 1})
        assert await locks_module.get_idempotent_response("key-1") == {"a": 1}

    @pytest.mark.asyncio
    async def test_missing_key_returns_none(self, monkeypatch):
        fake = _FakeRedis()
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        assert await locks_module.get_idempotent_response("nope") is None

    @pytest.mark.asyncio
    async def test_get_degrades_to_none_when_unavailable(self, monkeypatch):
        fake = _FakeRedis(raise_on_connect=True)
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        assert await locks_module.get_idempotent_response("key-1") is None

    @pytest.mark.asyncio
    async def test_store_does_not_raise_when_unavailable(self, monkeypatch):
        fake = _FakeRedis(raise_on_connect=True)
        monkeypatch.setattr(locks_module, "get_redis_client", lambda: fake)
        await locks_module.store_idempotent_response(
            "key-1", {"a": 1}
        )  # should not raise
