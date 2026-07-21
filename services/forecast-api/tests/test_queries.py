"""Tests for ecolens_forecast_api.queries.

Asserts the query stays a single-table, no-join SELECT with exactly
the columns the baseline forecaster needs.
"""

from __future__ import annotations

import pytest

from conftest import FakeConnectionPool
from ecolens_forecast_api.queries import get_latest_feature_row


@pytest.mark.asyncio
async def test_queries_ml_features_demand_v1_only():
    pool = FakeConnectionPool(fetchrow_result={"ts_30": "2026-07-21T12:00:00Z"})
    await get_latest_feature_row(pool, "NSW1")
    query, args = pool.calls[0]
    assert "FROM ml_features_demand_v1" in query
    assert "JOIN" not in query.upper()
    assert args == ("NSW1",)


@pytest.mark.asyncio
async def test_selects_all_48_lag_columns():
    pool = FakeConnectionPool(fetchrow_result=None)
    await get_latest_feature_row(pool, "NSW1")
    query, _ = pool.calls[0]
    assert "demand_lag_01" in query
    assert "demand_lag_48" in query
    assert "demand_lag_49" not in query


@pytest.mark.asyncio
async def test_returns_none_when_no_data():
    pool = FakeConnectionPool(fetchrow_result=None)
    result = await get_latest_feature_row(pool, "NSW1")
    assert result is None


@pytest.mark.asyncio
async def test_orders_by_ts_30_desc_limit_1():
    pool = FakeConnectionPool(fetchrow_result=None)
    await get_latest_feature_row(pool, "NSW1")
    query, _ = pool.calls[0]
    assert "ORDER BY ts_30 DESC" in query
    assert "LIMIT 1" in query
