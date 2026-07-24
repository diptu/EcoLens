"""Tests for ecolens.warehouse.api.db.ConnectionPool.

Uses a fake asyncpg-shaped pool/connection (from conftest.py) so these
never touch a real PostgreSQL server.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from conftest import FakeAsyncpgConn, FakeAsyncpgPool
from ecolens.warehouse.api.db import ConnectionPool, check_health
from ecolens.warehouse.api.settings import WarehouseApiSettings


@pytest.fixture
def pool() -> ConnectionPool:
    return ConnectionPool(WarehouseApiSettings())


class TestNotConnected:
    @pytest.mark.asyncio
    async def test_health_reports_unavailable(self, pool: ConnectionPool):
        result = await pool.health()
        assert result["status"] == "unavailable"

    @pytest.mark.asyncio
    async def test_fetch_raises_503(self, pool: ConnectionPool):
        with pytest.raises(HTTPException) as exc_info:
            await pool.fetch("SELECT 1")
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_fetchrow_raises_503(self, pool: ConnectionPool):
        with pytest.raises(HTTPException) as exc_info:
            await pool.fetchrow("SELECT 1")
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_fetchval_raises_503(self, pool: ConnectionPool):
        with pytest.raises(HTTPException) as exc_info:
            await pool.fetchval("SELECT 1")
        assert exc_info.value.status_code == 503

    def test_is_connected_false(self, pool: ConnectionPool):
        assert pool.is_connected is False


class TestConnected:
    @pytest.mark.asyncio
    async def test_health_ok(self, pool: ConnectionPool):
        pool._pool = FakeAsyncpgPool(FakeAsyncpgConn(fetchval_results=[1]))  # type: ignore[assignment]
        result = await pool.health()
        assert result["status"] == "ok"
        assert "latency_ms" in result

    @pytest.mark.asyncio
    async def test_health_error_when_query_fails(self, pool: ConnectionPool):
        pool._pool = FakeAsyncpgPool(FakeAsyncpgConn(raises=RuntimeError("boom")))  # type: ignore[assignment]
        result = await pool.health()
        assert result["status"] == "error"
        assert "boom" in result["error"]

    @pytest.mark.asyncio
    async def test_fetch_returns_list_of_dicts(self, pool: ConnectionPool):
        pool._pool = FakeAsyncpgPool(  # type: ignore[assignment]
            FakeAsyncpgConn(fetch_result=[{"region": "NSW1"}])
        )
        rows = await pool.fetch("SELECT * FROM dim_region")
        assert rows == [{"region": "NSW1"}]

    @pytest.mark.asyncio
    async def test_fetch_wraps_query_error_as_503(self, pool: ConnectionPool):
        pool._pool = FakeAsyncpgPool(FakeAsyncpgConn(raises=RuntimeError("boom")))  # type: ignore[assignment]
        with pytest.raises(HTTPException) as exc_info:
            await pool.fetch("SELECT 1")
        assert exc_info.value.status_code == 503

    @pytest.mark.asyncio
    async def test_fetchrow_returns_none_when_no_row(self, pool: ConnectionPool):
        pool._pool = FakeAsyncpgPool(FakeAsyncpgConn())  # type: ignore[assignment]
        assert await pool.fetchrow("SELECT 1") is None

    @pytest.mark.asyncio
    async def test_fetchrow_returns_dict(self, pool: ConnectionPool):
        pool._pool = FakeAsyncpgPool(  # type: ignore[assignment]
            FakeAsyncpgConn(fetchrow_results=[{"region": "NSW1"}])
        )
        assert await pool.fetchrow("SELECT 1") == {"region": "NSW1"}

    @pytest.mark.asyncio
    async def test_disconnect_closes_and_resets(self, pool: ConnectionPool):
        fake = FakeAsyncpgPool()
        pool._pool = fake  # type: ignore[assignment]
        await pool.disconnect()
        assert fake.closed is True
        assert pool.is_connected is False

    def test_is_connected_true(self, pool: ConnectionPool):
        pool._pool = FakeAsyncpgPool()  # type: ignore[assignment]
        assert pool.is_connected is True


@pytest.mark.asyncio
async def test_check_health_degrades_when_create_pool_fails(monkeypatch):
    import ecolens.warehouse.api.db as db_module

    async def failing_create_pool(*args, **kwargs):
        raise OSError("connection refused")

    monkeypatch.setattr(db_module.asyncpg, "create_pool", failing_create_pool)
    result = await check_health()
    assert result["status"] == "error"
