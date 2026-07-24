"""Tests for ecolens.warehouse.api.queries — verifies each helper calls the
pool correctly and shapes its result, using the FakeConnectionPool double
from conftest.py instead of a real PostgreSQL connection.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from conftest import FakeConnectionPool

from ecolens.warehouse.api import queries

SINCE = datetime(2026, 1, 1, tzinfo=timezone.utc)
UNTIL = datetime(2026, 1, 2, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_get_regions_calls_fetch_with_no_args():
    pool = FakeConnectionPool(fetch_result=[{"region": "NSW1", "state": "NSW"}])
    result = await queries.get_regions(pool)
    assert result == [{"region": "NSW1", "state": "NSW"}]
    assert pool.calls[0][0] == "fetch"
    assert pool.calls[0][2] == ()


@pytest.mark.asyncio
async def test_get_demand_timeseries_passes_region_range_limit():
    pool = FakeConnectionPool(fetch_result=[{"ts": SINCE, "region": "NSW1"}])
    result = await queries.get_demand_timeseries(pool, "NSW1", SINCE, UNTIL, limit=500)
    assert result == [{"ts": SINCE, "region": "NSW1"}]
    assert pool.calls[0][2] == ("NSW1", SINCE, UNTIL, 500)


@pytest.mark.asyncio
async def test_get_generation_mix_passes_args():
    pool = FakeConnectionPool(fetch_result=[])
    await queries.get_generation_mix(pool, "VIC1", SINCE, UNTIL, limit=100)
    assert pool.calls[0][2] == ("VIC1", SINCE, UNTIL, 100)


@pytest.mark.asyncio
async def test_get_weather_joined_passes_args():
    pool = FakeConnectionPool(fetch_result=[])
    await queries.get_weather_joined(pool, "QLD1", SINCE, UNTIL, limit=100)
    assert pool.calls[0][2] == ("QLD1", SINCE, UNTIL, 100)


@pytest.mark.asyncio
async def test_get_demand_summary_merges_region_since_until():
    pool = FakeConnectionPool(fetchrow_result={"n_obs": 48, "avg_demand_mw": 5000.0})
    result = await queries.get_demand_summary(pool, "NSW1", SINCE, UNTIL)
    assert result["region"] == "NSW1"
    assert result["since"] == SINCE
    assert result["until"] == UNTIL
    assert result["n_obs"] == 48
    assert result["avg_demand_mw"] == 5000.0


@pytest.mark.asyncio
async def test_get_demand_summary_empty_row_returns_empty_dict():
    pool = FakeConnectionPool(fetchrow_result=None)
    result = await queries.get_demand_summary(pool, "NSW1", SINCE, UNTIL)
    assert result == {}


@pytest.mark.asyncio
async def test_get_national_demand_passes_args():
    pool = FakeConnectionPool(fetch_result=[])
    await queries.get_national_demand(pool, SINCE, UNTIL, limit=42)
    assert pool.calls[0][2] == (SINCE, UNTIL, 42)


@pytest.mark.asyncio
async def test_get_ml_features_passes_args():
    pool = FakeConnectionPool(fetch_result=[])
    await queries.get_ml_features(pool, "SA1", SINCE, UNTIL, limit=10)
    assert pool.calls[0][2] == ("SA1", SINCE, UNTIL, 10)


@pytest.mark.asyncio
async def test_get_latest_features_defaults_to_48_rows():
    pool = FakeConnectionPool(fetch_result=[])
    await queries.get_latest_features(pool, "TAS1")
    assert pool.calls[0][2] == ("TAS1", 48)


@pytest.mark.asyncio
async def test_get_holidays_without_region_omits_region_arg():
    pool = FakeConnectionPool(fetch_result=[])
    await queries.get_holidays(pool, 2026)
    # (today, year) -- no region
    assert len(pool.calls[0][2]) == 2


@pytest.mark.asyncio
async def test_get_holidays_with_region_includes_region_arg():
    pool = FakeConnectionPool(fetch_result=[])
    await queries.get_holidays(pool, 2026, region="NSW1")
    assert pool.calls[0][2][0] == "NSW1"


@pytest.mark.asyncio
async def test_get_holidays_casts_days_until_to_int():
    pool = FakeConnectionPool(
        fetch_result=[{"date": "2026-12-25", "days_until": 157.0}]
    )
    result = await queries.get_holidays(pool, 2026)
    assert result[0]["days_until"] == 157
    assert isinstance(result[0]["days_until"], int)


@pytest.mark.asyncio
async def test_get_holidays_none_days_until_stays_none():
    pool = FakeConnectionPool(fetch_result=[{"date": "2026-12-25", "days_until": None}])
    result = await queries.get_holidays(pool, 2026)
    assert result[0]["days_until"] is None
