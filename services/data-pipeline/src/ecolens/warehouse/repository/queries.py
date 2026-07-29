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

from ecolens.warehouse.db.connection import ConnectionPool


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


async def get_national_summary(
    pool: ConnectionPool,
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    """National (all-region) single-number summary over `[since, until)` --
    root TODO.md's Dashboard/Executive Tier 2: neither `get_demand_summary`
    (per-region) nor `get_national_demand` (a national *time series*, not
    a single summary) gives this directly, and critically neither computes
    real **mass** emissions (tCO2e) -- both only ever expose the *rate*
    column `emissions_intensity_kgco2e_per_mwh`.

    `national_series` sums demand *per 30-min slot across regions first*,
    then aggregates that series -- `peak_demand_mw` is the highest
    national (summed) demand at any one slot, not the highest single
    region's own demand, which a naive `MAX(demand_mw)` over every
    `(region, ts_30)` row would silently give instead.

    `total_carbon_tco2e` is computed directly against the base
    (non-aggregated) rows -- `SUM(region_demand * 0.5h * region_intensity)`
    across every `(region, ts_30)` row in range is exact regardless of
    grouping, whereas computing it from `national_series` would need
    each slot's national demand times an *unweighted average* of that
    slot's per-region intensities, which is not the same number (a
    region with high demand and a region with high intensity don't
    necessarily coincide).
    """
    row = await pool.fetchrow(
        "WITH national_series AS ("
        "  SELECT ts_30, SUM(demand_mw) AS demand_mw "
        "  FROM fact_demand_30min "
        "  WHERE ts_30 >= $1 AND ts_30 < $2 "
        "  GROUP BY ts_30"
        "), "
        "series_agg AS ("
        "  SELECT "
        "    COUNT(*) AS n_slots, "
        "    AVG(demand_mw) AS avg_demand_mw, "
        "    MAX(demand_mw) AS peak_demand_mw, "
        "    MIN(demand_mw) AS min_demand_mw, "
        "    SUM(demand_mw) * 0.5 AS total_energy_mwh "
        "  FROM national_series"
        "), "
        "peak AS ("
        "  SELECT ts_30 AS peak_ts FROM national_series "
        "  ORDER BY demand_mw DESC NULLS LAST LIMIT 1"
        "), "
        "raw_totals AS ("
        "  SELECT "
        "    SUM(demand_mw * 0.5 * emissions_intensity_kgco2e_per_mwh) / 1000.0 "
        "      AS total_carbon_tco2e, "
        "    AVG(renewable_proportion) AS avg_renewable_proportion, "
        "    AVG(emissions_intensity_kgco2e_per_mwh) AS avg_emissions_intensity_kgco2e_per_mwh "
        "  FROM fact_demand_30min "
        "  WHERE ts_30 >= $1 AND ts_30 < $2"
        ") "
        "SELECT series_agg.*, peak.peak_ts, raw_totals.* "
        "FROM series_agg, peak, raw_totals",
        since,
        until,
    )
    if not row:
        return {}
    return {"since": since, "until": until, **row}


async def get_national_daily_emissions(
    pool: ConnectionPool,
    since: date,
    limit: int = 90,
) -> list[dict[str, Any]]:
    """Daily-bucketed national actuals from `mv_daily_national_emissions`
    (root TODO.md's Dashboard/Executive Tier 2 trend-chart "Actual"
    line) -- the true national sibling of the existing
    `mv_daily_national_demand` (which is grouped by day *and region*,
    not truly national, and carries no emissions columns).
    """
    return await pool.fetch(
        "SELECT date_local, total_demand_mwh, avg_renewable_proportion, "
        "  avg_emissions_intensity_kgco2e_per_mwh, total_carbon_tco2e "
        "FROM mv_daily_national_emissions "
        "WHERE date_local >= $1 "
        "ORDER BY date_local "
        "LIMIT $2",
        since,
        limit,
    )


# The 13 fuel-type columns that sum to a demand-serving total -- same
# `GENERATION_COLUMNS` exclusion as data-pipeline's
# `forecasting.service.normalization` (battery_charge_mw is a load, not
# generation; the two curtailment_* columns are foregone, not delivered,
# energy) -- kept as a plain literal here rather than importing across
# the warehouse/forecasting service boundary for one shared constant.
_GENERATION_MIX_COLUMNS: tuple[str, ...] = (
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
)


async def get_national_generation_mix(
    pool: ConnectionPool,
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    """National (summed across every region) fuel-mix totals over
    `[since, until)`, for root TODO.md's Dashboard/Executive Tier 2
    "Emissions by Source" donut's Grid Electricity slice -- the grid's
    own generation mix (interpretation (a) in that TODO item), not a
    specific customer's purchased-electricity attribution (interpretation
    (b), which needs the not-yet-built customer-meter ingestion in that
    same item's Tier 3 cross-reference).
    """
    select_cols = ", ".join(f"SUM({c}) AS {c}" for c in _GENERATION_MIX_COLUMNS)
    row = await pool.fetchrow(
        f"SELECT {select_cols} "  # nosec B608 - _GENERATION_MIX_COLUMNS is a fixed internal literal tuple, not user input
        "FROM fact_generation_30min "
        "WHERE ts_30 >= $1 AND ts_30 < $2",
        since,
        until,
    )
    if not row:
        return {}
    values = {c: (row[c] or 0.0) for c in _GENERATION_MIX_COLUMNS}
    total = sum(values.values())
    shares = {c: (v / total if total > 0 else 0.0) for c, v in values.items()}
    return {
        "since": since,
        "until": until,
        "total_mw": total,
        "mix_mw": values,
        "mix_share": shares,
    }


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
    *,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Returns `(page, total)` -- `total` is the full match count for
    `year`/`region` *before* `limit`/`offset` are applied, via a
    separate `COUNT(*)` rather than a `COUNT(*) OVER()` window column:
    a window column would silently report 0 once `offset` runs past the
    last matching row (zero rows come back at all), which is exactly
    the case a caller paging to the end needs `total` to still be
    correct for.
    """
    today = date.today()
    if region:
        total = await pool.fetchval(
            "SELECT COUNT(*) FROM dim_holiday "
            "WHERE region = $1 AND EXTRACT(YEAR FROM date) = $2",
            region,
            year,
        )
        rows = await pool.fetch(
            "SELECT date, region, state, holiday_name, holiday_type, is_observed, "
            "  (date - $2::date) AS days_until "
            "FROM dim_holiday "
            "WHERE region = $1 AND EXTRACT(YEAR FROM date) = $3 "
            "ORDER BY date "
            "LIMIT $4 OFFSET $5",
            region,
            today,
            year,
            limit,
            offset,
        )
    else:
        total = await pool.fetchval(
            "SELECT COUNT(*) FROM dim_holiday WHERE EXTRACT(YEAR FROM date) = $1",
            year,
        )
        rows = await pool.fetch(
            "SELECT date, region, state, holiday_name, holiday_type, is_observed, "
            "  (date - $1::date) AS days_until "
            "FROM dim_holiday "
            "WHERE EXTRACT(YEAR FROM date) = $2 "
            "ORDER BY date, region "
            "LIMIT $3 OFFSET $4",
            today,
            year,
            limit,
            offset,
        )
    items = [
        {
            **r,
            "days_until": int(r["days_until"])
            if r.get("days_until") is not None
            else None,
        }
        for r in rows
    ]
    return items, total or 0


async def get_carbon_summary(
    pool: ConnectionPool,
    regions: tuple[str, ...],
    since: datetime,
    until: datetime,
) -> dict[str, Any]:
    """Single-row rollup over `[since, until)` for exactly `regions` --
    `/api/analytics/executive-kpis`'s own query, region-list-parameterized
    unlike `get_national_summary` above (unconditionally all-region, in
    practice NEM+WEM combined) or `get_demand_summary` (single region).
    Neither fits without a region filter added, since this endpoint
    needs both ("NEM" = 5 regions, a single region = 1) -- see
    `warehouse.core.regions.resolve_region_group`.

    Returns `total_carbon_tco2e` (real mass emissions, same per-row
    computation `get_national_summary` documents the reasoning for),
    `avg_emissions_intensity_kgco2e_per_mwh` (numerically == g/kWh),
    `avg_renewable_proportion` (0..100, already-percentage per
    `RENEWABLE_CANONICAL_COLUMNS`'s ingestion-time computation), and
    `total_energy_mwh`. Empty dict (not an exception) when the range has
    no rows -- e.g. a `previous` window before any data was ingested --
    so callers treat "no prior data" the same way they'd treat "no
    prior period," not as a crash.
    """
    row = await pool.fetchrow(
        "SELECT "
        "  SUM(demand_mw * 0.5 * emissions_intensity_kgco2e_per_mwh) / 1000.0 "
        "    AS total_carbon_tco2e, "
        "  AVG(emissions_intensity_kgco2e_per_mwh) "
        "    AS avg_emissions_intensity_kgco2e_per_mwh, "
        "  AVG(renewable_proportion) AS avg_renewable_proportion, "
        "  SUM(demand_mw) * 0.5 AS total_energy_mwh "
        "FROM fact_demand_30min "
        "WHERE region = ANY($1::text[]) AND ts_30 >= $2 AND ts_30 < $3",
        list(regions),
        since,
        until,
    )
    if not row or row.get("total_energy_mwh") is None:
        return {}
    return dict(row)


async def get_daily_carbon_series(
    pool: ConnectionPool,
    regions: tuple[str, ...],
    since: datetime,
    until: datetime,
) -> list[dict[str, Any]]:
    """Day-bucketed series over `[since, until)` for exactly `regions` --
    the raw material `service/executive_kpis.py` downsamples into each
    KPI card's `sparkline`. Same fixed-AEST (`Australia/Brisbane`)
    day-bucketing convention `mv_daily_national_emissions.sql` uses and
    documents the reasoning for (AEMO's own NEM settlement-day
    convention) -- kept as a live query here rather than a materialized
    view since this needs a region filter that view's fixed all-region
    grain can't express.
    """
    rows = await pool.fetch(
        "SELECT "
        "  (ts_30 AT TIME ZONE 'Australia/Brisbane')::date AS date_local, "
        "  SUM(demand_mw * 0.5 * emissions_intensity_kgco2e_per_mwh) / 1000.0 "
        "    AS total_carbon_tco2e, "
        "  AVG(emissions_intensity_kgco2e_per_mwh) "
        "    AS avg_emissions_intensity_kgco2e_per_mwh, "
        "  AVG(renewable_proportion) AS avg_renewable_proportion "
        "FROM fact_demand_30min "
        "WHERE region = ANY($1::text[]) AND ts_30 >= $2 AND ts_30 < $3 "
        "GROUP BY date_local "
        "ORDER BY date_local",
        list(regions),
        since,
        until,
    )
    return rows


__all__ = [
    "get_regions",
    "get_demand_timeseries",
    "get_generation_mix",
    "get_weather_joined",
    "get_demand_summary",
    "get_national_demand",
    "get_national_summary",
    "get_national_daily_emissions",
    "get_national_generation_mix",
    "get_ml_features",
    "get_latest_features",
    "get_holidays",
    "get_carbon_summary",
    "get_daily_carbon_series",
]
