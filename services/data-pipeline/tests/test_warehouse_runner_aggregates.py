"""Tests for ecolens.warehouse.runner.aggregates.AggregateRefresher."""

from __future__ import annotations

import pytest

from conftest import FakeAsyncpgConn, FakeAsyncpgPool
from ecolens.warehouse.runner.aggregates import VIEWS, AggregateRefresher
from ecolens.warehouse.runner.settings import WarehouseRunnerSettings


@pytest.fixture
def refresher() -> AggregateRefresher:
    return AggregateRefresher(WarehouseRunnerSettings())


class TestNotConnected:
    @pytest.mark.asyncio
    async def test_refresh_skips_when_not_connected(
        self, refresher: AggregateRefresher
    ):
        result = await refresher.refresh()
        assert result.success is True
        assert result.metrics.get("status") == "skipped"


class TestRefresh:
    @pytest.mark.asyncio
    async def test_refreshes_all_existing_views(self, refresher: AggregateRefresher):
        conn = FakeAsyncpgConn(fetchval_results=[1, 1, 1])
        refresher._pool = FakeAsyncpgPool(conn)
        result = await refresher.refresh()
        assert result.success is True
        assert result.rows_affected == len(VIEWS)
        assert len(conn.executed) == len(VIEWS)
        for view in VIEWS:
            assert any(view in stmt for stmt in conn.executed)

    @pytest.mark.asyncio
    async def test_skips_views_that_do_not_exist(self, refresher: AggregateRefresher):
        conn = FakeAsyncpgConn(fetchval_results=[None, None, None])
        refresher._pool = FakeAsyncpgPool(conn)
        result = await refresher.refresh()
        assert result.success is True
        assert result.rows_affected == 0
        assert conn.executed == []

    @pytest.mark.asyncio
    async def test_mixed_existing_and_missing_views(
        self, refresher: AggregateRefresher
    ):
        conn = FakeAsyncpgConn(fetchval_results=[1, None, 1])
        refresher._pool = FakeAsyncpgPool(conn)
        result = await refresher.refresh()
        assert result.rows_affected == 2

    @pytest.mark.asyncio
    async def test_query_error_returns_failed_stage(
        self, refresher: AggregateRefresher
    ):
        refresher._pool = FakeAsyncpgPool(FakeAsyncpgConn(raises=RuntimeError("boom")))
        result = await refresher.refresh()
        assert result.success is False
        assert "boom" in (result.error or "")
