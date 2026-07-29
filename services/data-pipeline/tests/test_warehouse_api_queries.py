"""Tests for ecolens.warehouse.repository.queries — verifies each helper calls the
pool correctly and shapes its result, using the FakeConnectionPool double
from conftest.py instead of a real PostgreSQL connection.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from conftest import FakeConnectionPool

from ecolens.warehouse.repository import queries

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
async def test_get_national_summary_merges_since_until():
    pool = FakeConnectionPool(
        fetchrow_result={
            "n_slots": 48,
            "avg_demand_mw": 25000.0,
            "peak_demand_mw": 30000.0,
            "peak_ts": SINCE,
            "min_demand_mw": 20000.0,
            "total_energy_mwh": 1_200_000.0,
            "avg_renewable_proportion": 25.0,
            "avg_emissions_intensity_kgco2e_per_mwh": 700.0,
            "total_carbon_tco2e": 840.0,
        }
    )
    result = await queries.get_national_summary(pool, SINCE, UNTIL)
    assert result["since"] == SINCE
    assert result["until"] == UNTIL
    assert result["n_slots"] == 48
    assert result["total_carbon_tco2e"] == 840.0
    assert pool.calls[0][0] == "fetchrow"
    assert pool.calls[0][2] == (SINCE, UNTIL)


@pytest.mark.asyncio
async def test_get_national_summary_empty_row_returns_empty_dict():
    pool = FakeConnectionPool(fetchrow_result=None)
    result = await queries.get_national_summary(pool, SINCE, UNTIL)
    assert result == {}


@pytest.mark.asyncio
async def test_get_national_daily_emissions_passes_since_and_limit():
    pool = FakeConnectionPool(
        fetch_result=[{"date_local": SINCE.date(), "total_demand_mwh": 500_000.0}]
    )
    result = await queries.get_national_daily_emissions(pool, SINCE.date(), limit=30)
    assert result[0]["total_demand_mwh"] == 500_000.0
    assert pool.calls[0][2] == (SINCE.date(), 30)


@pytest.mark.asyncio
async def test_get_national_daily_emissions_defaults_to_90_days():
    pool = FakeConnectionPool(fetch_result=[])
    await queries.get_national_daily_emissions(pool, SINCE.date())
    assert pool.calls[0][2] == (SINCE.date(), 90)


@pytest.mark.asyncio
async def test_get_national_generation_mix_computes_shares():
    pool = FakeConnectionPool(
        fetchrow_result={
            "coal_black_mw": 100.0,
            "coal_brown_mw": 0.0,
            "gas_ccgt_mw": 0.0,
            "gas_ocgt_mw": 0.0,
            "gas_other_mw": 0.0,
            "hydro_mw": 0.0,
            "pumped_hydro_mw": 0.0,
            "wind_mw": 100.0,
            "solar_utility_mw": 0.0,
            "solar_rooftop_mw": 0.0,
            "biomass_mw": 0.0,
            "distillate_mw": 0.0,
            "battery_discharge_mw": 0.0,
        }
    )
    result = await queries.get_national_generation_mix(pool, SINCE, UNTIL)
    assert result["total_mw"] == 200.0
    assert result["mix_mw"]["coal_black_mw"] == 100.0
    assert result["mix_share"]["coal_black_mw"] == pytest.approx(0.5)
    assert result["mix_share"]["wind_mw"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_get_national_generation_mix_zero_total_does_not_divide_by_zero():
    pool = FakeConnectionPool(
        fetchrow_result=dict.fromkeys(
            [
                "coal_black_mw",
                "coal_brown_mw",
                "gas_ccgt_mw",
                "gas_ocgt_mw",
                "gas_other_mw",
                "hydro_mw",
                "pumped_hydro_mw",
                "wind_mw",
                "solar_utility_mw",
                "solar_rooftop_mw",
                "biomass_mw",
                "distillate_mw",
                "battery_discharge_mw",
            ],
            None,
        )
    )
    result = await queries.get_national_generation_mix(pool, SINCE, UNTIL)
    assert result["total_mw"] == 0.0
    assert all(v == 0.0 for v in result["mix_share"].values())


@pytest.mark.asyncio
async def test_get_national_generation_mix_empty_row_returns_empty_dict():
    pool = FakeConnectionPool(fetchrow_result=None)
    result = await queries.get_national_generation_mix(pool, SINCE, UNTIL)
    assert result == {}


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
    pool = FakeConnectionPool(fetch_result=[], fetchval_result=0)
    await queries.get_holidays(pool, 2026)
    fetch_call = next(c for c in pool.calls if c[0] == "fetch")
    # (today, year, limit, offset) -- no region
    assert len(fetch_call[2]) == 4


@pytest.mark.asyncio
async def test_get_holidays_with_region_includes_region_arg():
    pool = FakeConnectionPool(fetch_result=[], fetchval_result=0)
    await queries.get_holidays(pool, 2026, region="NSW1")
    fetch_call = next(c for c in pool.calls if c[0] == "fetch")
    assert fetch_call[2][0] == "NSW1"


@pytest.mark.asyncio
async def test_get_holidays_defaults_to_limit_100_offset_0():
    pool = FakeConnectionPool(fetch_result=[], fetchval_result=0)
    await queries.get_holidays(pool, 2026)
    fetch_call = next(c for c in pool.calls if c[0] == "fetch")
    assert fetch_call[2][-2:] == (100, 0)


@pytest.mark.asyncio
async def test_get_holidays_passes_custom_limit_and_offset():
    pool = FakeConnectionPool(fetch_result=[], fetchval_result=0)
    await queries.get_holidays(pool, 2026, region="NSW1", limit=10, offset=5)
    fetch_call = next(c for c in pool.calls if c[0] == "fetch")
    assert fetch_call[2][-2:] == (10, 5)


@pytest.mark.asyncio
async def test_get_holidays_returns_total_from_count_query():
    pool = FakeConnectionPool(fetch_result=[], fetchval_result=42)
    items, total = await queries.get_holidays(pool, 2026)
    assert items == []
    assert total == 42
    assert pool.calls[0][0] == "fetchval"


@pytest.mark.asyncio
async def test_get_holidays_casts_days_until_to_int():
    pool = FakeConnectionPool(
        fetch_result=[{"date": "2026-12-25", "days_until": 157.0}],
        fetchval_result=1,
    )
    items, _total = await queries.get_holidays(pool, 2026)
    assert items[0]["days_until"] == 157
    assert isinstance(items[0]["days_until"], int)


@pytest.mark.asyncio
async def test_get_holidays_none_days_until_stays_none():
    pool = FakeConnectionPool(
        fetch_result=[{"date": "2026-12-25", "days_until": None}],
        fetchval_result=1,
    )
    items, _total = await queries.get_holidays(pool, 2026)
    assert items[0]["days_until"] is None


class TestGetCarbonSummary:
    """`/api/analytics/executive-kpis`'s own query -- region-list-
    parameterized, unlike `get_national_summary` (unconditionally
    all-region) or `get_demand_summary` (single region) above.
    """

    @pytest.mark.asyncio
    async def test_happy_path_returns_row_as_dict(self):
        pool = FakeConnectionPool(
            fetchrow_result={
                "total_carbon_tco2e": 840.0,
                "avg_emissions_intensity_kgco2e_per_mwh": 700.0,
                "avg_renewable_proportion": 25.0,
                "total_energy_mwh": 1_200_000.0,
            }
        )
        result = await queries.get_carbon_summary(pool, ("NSW1", "QLD1"), SINCE, UNTIL)
        assert result["total_carbon_tco2e"] == 840.0

    @pytest.mark.asyncio
    async def test_region_list_and_range_are_passed_through(self):
        pool = FakeConnectionPool(fetchrow_result={"total_energy_mwh": 1.0})
        await queries.get_carbon_summary(pool, ("NSW1", "QLD1"), SINCE, UNTIL)
        _, _, args = pool.calls[0]
        assert args == (["NSW1", "QLD1"], SINCE, UNTIL)

    @pytest.mark.asyncio
    async def test_no_matching_rows_returns_empty_dict(self):
        # SUM/AVG over zero matching rows still returns one row of NULLs,
        # not zero rows -- total_energy_mwh is the sentinel this function
        # checks to tell "no data" apart from "data, but it's all zero."
        pool = FakeConnectionPool(
            fetchrow_result={
                "total_carbon_tco2e": None,
                "avg_emissions_intensity_kgco2e_per_mwh": None,
                "avg_renewable_proportion": None,
                "total_energy_mwh": None,
            }
        )
        result = await queries.get_carbon_summary(pool, ("WEM",), SINCE, UNTIL)
        assert result == {}


class TestGetDailyCarbonSeries:
    @pytest.mark.asyncio
    async def test_happy_path_returns_rows(self):
        pool = FakeConnectionPool(
            fetch_result=[
                {
                    "date_local": "2026-01-01",
                    "total_carbon_tco2e": 100.0,
                    "avg_emissions_intensity_kgco2e_per_mwh": 700.0,
                    "avg_renewable_proportion": 20.0,
                }
            ]
        )
        result = await queries.get_daily_carbon_series(pool, ("NSW1",), SINCE, UNTIL)
        assert result[0]["total_carbon_tco2e"] == 100.0

    @pytest.mark.asyncio
    async def test_empty_history_returns_empty_list(self):
        pool = FakeConnectionPool(fetch_result=[])
        result = await queries.get_daily_carbon_series(pool, ("WEM",), SINCE, UNTIL)
        assert result == []
