"""Query helpers, one per warehouse table/route.

All queries assume the dbt project has been run and `dim_region`,
`fact_demand_30min`, `dim_holiday`, `ml_features_demand_v1` exist (see
`warehouse/werehouse.md`). If they don't, `ConnectionPool` surfaces a
503 rather than a raw asyncpg error (see db.py). Every timeseries
query orders/filters on `ts_30` (the mart's 30-min bucket key) but
still returns the display `ts` column.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from .db import ConnectionPool


async def get_regions(pool: ConnectionPool) -> list[dict[str, Any]]:
    """List all NEM/WEM regions with their state, population, and tz."""
    return await pool.fetch(
        "SELECT region, state, population, timezone FROM dim_region ORDER BY region"
    )


async def get_demand_timeseries(
    pool: ConnectionPool,
    region: str,
    since: datetime,
    until: datetime,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    return await pool.fetch(
        "SELECT ts, region, demand_mw, price_mwh, renewable_proportion, "
        "emissions_intensity_kgco2e_per_mwh, temp_c, humidity_pct, is_holiday "
        "FROM fact_demand_30min "
        "WHERE region = $1 AND ts_30 >= $2 AND ts_30 < $3 "
        "ORDER BY ts_30 "
        "LIMIT $4",
        region,
        since,
        until,
        limit,
    )


async def get_generation_mix(
    pool: ConnectionPool,
    region: str,
    since: datetime,
    until: datetime,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    return await pool.fetch(
        "SELECT ts, region, coal_black_mw, coal_brown_mw, gas_ccgt_mw, gas_ocgt_mw, "
        "wind_mw, solar_utility_mw, solar_rooftop_mw, battery_discharge_mw, "
        "hydro_mw, biomass_mw, total_generation_mw "
        "FROM fact_demand_30min "
        "WHERE region = $1 AND ts_30 >= $2 AND ts_30 < $3 "
        "ORDER BY ts_30 "
        "LIMIT $4",
        region,
        since,
        until,
        limit,
    )


async def get_weather_joined(
    pool: ConnectionPool,
    region: str,
    since: datetime,
    until: datetime,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    return await pool.fetch(
        "SELECT ts, region, temp_c, apparent_temp_c, humidity_pct, wind_speed_kmh, "
        "wind_direction_deg, wind_gust_kmh, pressure_hpa, rain_since_9am_mm "
        "FROM fact_demand_30min "
        "WHERE region = $1 AND ts_30 >= $2 AND ts_30 < $3 "
        "ORDER BY ts_30 "
        "LIMIT $4",
        region,
        since,
        until,
        limit,
    )


async def get_demand_summary(
    pool: ConnectionPool,
    region: str,
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    row = await pool.fetchrow(
        "SELECT "
        "  COUNT(*) AS n_obs, "
        "  AVG(demand_mw) AS avg_demand_mw, "
        "  MAX(demand_mw) AS peak_demand_mw, "
        "  MIN(demand_mw) AS min_demand_mw, "
        "  SUM(demand_mw) * 0.5 AS total_energy_mwh, "  # 30-min intervals -> MWh = MW * 0.5h
        "  AVG(price_mwh) AS avg_price_mwh, "
        "  AVG(renewable_proportion) AS avg_renewable_proportion, "
        "  AVG(temp_c) AS avg_temp_c, "
        "  (SELECT ts_30 FROM fact_demand_30min "
        "   WHERE region = $1 AND ts_30 >= $2 AND ts_30 < $3 "
        "   ORDER BY demand_mw DESC NULLS LAST LIMIT 1) AS peak_ts "
        "FROM fact_demand_30min "
        "WHERE region = $1 AND ts_30 >= $2 AND ts_30 < $3",
        region,
        since,
        until,
    )
    if not row:
        return {}
    return {"region": region, "since": since, "until": until, **row}


async def get_national_demand(
    pool: ConnectionPool,
    since: datetime,
    until: datetime,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    """All regions rolled up to a network-level time series."""
    return await pool.fetch(
        "SELECT ts_30, "
        "  SUM(demand_mw) AS demand_mw, "
        "  SUM(renewable_generation_mw) AS renewable_generation_mw, "
        "  SUM(total_generation_mw) AS total_generation_mw, "
        "  AVG(renewable_proportion) AS renewable_proportion, "
        "  AVG(emissions_intensity_kgco2e_per_mwh) AS emissions_intensity_kgco2e_per_mwh "
        "FROM fact_demand_30min "
        "WHERE ts_30 >= $1 AND ts_30 < $2 "
        "GROUP BY ts_30 "
        "ORDER BY ts_30 "
        "LIMIT $3",
        since,
        until,
        limit,
    )


async def get_ml_features(
    pool: ConnectionPool,
    region: str,
    since: datetime,
    until: datetime,
    limit: int = 10_000,
) -> list[dict[str, Any]]:
    return await pool.fetch(
        "SELECT * FROM ml_features_demand_v1 "
        "WHERE region = $1 AND ts_30 >= $2 AND ts_30 < $3 "
        "ORDER BY ts_30 "
        "LIMIT $4",
        region,
        since,
        until,
        limit,
    )


async def get_latest_features(
    pool: ConnectionPool,
    region: str,
    n: int = 48,
) -> list[dict[str, Any]]:
    """Most recent N rows (for inference — feeds the LSTM input window)."""
    return await pool.fetch(
        "SELECT * FROM ml_features_demand_v1 WHERE region = $1 ORDER BY ts_30 DESC LIMIT $2",
        region,
        n,
    )


async def get_holidays(
    pool: ConnectionPool,
    year: int,
    region: str | None = None,
) -> list[dict[str, Any]]:
    today = date.today()
    if region:
        rows = await pool.fetch(
            "SELECT date, region, state, holiday_name, holiday_type, is_observed, "
            "  EXTRACT(DAY FROM (date - $2::date)) AS days_until "
            "FROM dim_holiday "
            "WHERE region = $1 AND EXTRACT(YEAR FROM date) = $3 "
            "ORDER BY date",
            region,
            today,
            year,
        )
    else:
        rows = await pool.fetch(
            "SELECT date, region, state, holiday_name, holiday_type, is_observed, "
            "  EXTRACT(DAY FROM (date - $1::date)) AS days_until "
            "FROM dim_holiday "
            "WHERE EXTRACT(YEAR FROM date) = $2 "
            "ORDER BY date, region",
            today,
            year,
        )
    return [
        {
            **r,
            "days_until": int(r["days_until"])
            if r.get("days_until") is not None
            else None,
        }
        for r in rows
    ]


__all__ = [
    "get_regions",
    "get_demand_timeseries",
    "get_generation_mix",
    "get_weather_joined",
    "get_demand_summary",
    "get_national_demand",
    "get_ml_features",
    "get_latest_features",
    "get_holidays",
]
