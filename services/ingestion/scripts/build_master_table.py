#!/usr/bin/env python3
"""Build a local, wide, uniform-30-minute-grain `master` training table
from the shared staging file (`landed.duckdb`)'s 5 sources —
`openelectricity_mix`, `aemo_nem_dispatch`, `aemo_wem_dispatch`,
`bom_observations`, `aemo_holidays` — for local forecast-model
experimentation without hitting Neon Postgres.

Written to a **separate** file (`data/training/master.duckdb`), not into
the shared staging file itself — `pipeline.retention.prune_synced_history`
prunes rows out of `landed.duckdb` once they're synced to Postgres, and a
`master` table that lived there and got rebuilt from those same raw
tables would silently lose history every time pruning ran.

Grain: `(bucket_ts, region)`, `bucket_ts` = `ts` floored to a UTC-aligned
30-minute boundary (`time_bucket`). Every source's native cadence differs
(5-min for OE mix / AEMO NEM+WEM, ~10-30 min for BOM) — every numeric
column is the **mean** of whatever rows landed in that 30-minute bucket,
not a sum (these are power/rate readings, not cumulative energy; summing
would inflate a 30-minute bucket containing six 5-minute OE readings by
6x) and not last-observation (matches the simplest, most defensible
default for a first pass — deliberately no lag/rolling/cyclical features
baked in here, that's left to `app/service/ml/features.py::build_features`
or whatever the next feature-selection pass decides).

Deliberately not circular-mean for `wind_direction_deg` (a compass
bearing) — a plain arithmetic mean is wrong right at the 0/360 wrap
(e.g. 350° and 10° average to 180°, not ~0°), but correcting that is a
feature-selection-time concern, not a blocker for this first pass.

Weather is joined via `ASOF LEFT JOIN` (last BOM reading at-or-before
each bucket, per region), not an exact-bucket match — BOM reports
roughly hourly (confirmed: ~24.1 rows/station/day), so an exact match
against a 30-minute grid would leave every other bucket NULL by
construction, not because of an actual data gap. This mirrors
`int_demand_with_weather.sql`'s own LATERAL "last observation `&lt;=` ts"
pattern for the same reason. `aemo_holidays` is also `SELECT DISTINCT`-ed
before joining — the local staging file has no PK/dedup constraint and
holidays got landed repeatedly across separate ingest runs (confirmed:
930 raw rows, 90 distinct `(date, region)` pairs).

Output is a full rectangular panel: every 30-minute bucket that appears
anywhere in AEMO NEM/WEM demand, crossed with all 6 known regions — so
gaps show up as NULL rows rather than missing timestamps, matching a
regular time index a training pipeline can rely on.

Run from `services/ingestion/`:

    uv run python scripts/build_master_table.py
"""

from __future__ import annotations

from pathlib import Path

import click
import duckdb

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.service.pipeline.duckdb_staging import staging_path

log = get_logger(__name__)

_REGIONS = ["NSW1", "QLD1", "SA1", "TAS1", "VIC1", "WEM"]

_BUILD_SQL = """
CREATE OR REPLACE TABLE master AS
WITH aemo_demand AS (
    SELECT
        time_bucket(INTERVAL '30 minutes', ts) AS bucket_ts,
        region,
        avg(demand_mw) AS aemo_demand_mw,
        avg(price_mwh) AS aemo_price_mwh,
        avg(coal_mw) AS aemo_coal_mw,
        avg(gas_mw) AS aemo_gas_mw,
        avg(hydro_mw) AS aemo_hydro_mw,
        avg(wind_mw) AS aemo_wind_mw,
        avg(solar_utility_mw) AS aemo_solar_utility_mw,
        avg(solar_rooftop_mw) AS aemo_solar_rooftop_mw,
        avg(battery_mw) AS aemo_battery_mw,
        avg(net_import_mw) AS aemo_net_import_mw,
        avg(diesel_mw) AS aemo_diesel_mw,
        avg(biomass_mw) AS aemo_biomass_mw,
        avg(total_generation_mw) AS aemo_total_generation_mw
    FROM (
        SELECT
            ts, region, demand_mw, price_mwh, coal_mw, gas_mw, hydro_mw, wind_mw,
            solar_utility_mw, solar_rooftop_mw, battery_mw, net_import_mw,
            NULL::DOUBLE AS diesel_mw, NULL::DOUBLE AS biomass_mw,
            NULL::DOUBLE AS total_generation_mw
        FROM staging.aemo_nem_dispatch
        UNION ALL
        SELECT
            ts, region, demand_mw, price_mwh, coal_mw, gas_mw,
            NULL::DOUBLE AS hydro_mw, wind_mw, solar_utility_mw, solar_rooftop_mw,
            battery_mw, NULL::DOUBLE AS net_import_mw, diesel_mw, biomass_mw,
            total_generation_mw
        FROM staging.aemo_wem_dispatch
    )
    GROUP BY 1, 2
),
oe_mix AS (
    SELECT
        time_bucket(INTERVAL '30 minutes', ts) AS bucket_ts,
        region,
        avg(demand_mw) AS oe_demand_mw,
        avg(price_mwh) AS oe_price_mwh,
        avg(intensity_kg_per_mwh) AS oe_intensity_kg_per_mwh,
        avg(battery_discharge_mw) AS oe_battery_discharge_mw,
        avg(battery_charge_mw) AS oe_battery_charge_mw,
        avg(biomass_mw) AS oe_biomass_mw,
        avg(coal_mw) AS oe_coal_mw,
        avg(distillate_mw) AS oe_distillate_mw,
        avg(gas_mw) AS oe_gas_mw,
        avg(hydro_mw) AS oe_hydro_mw,
        avg(pumped_hydro_mw) AS oe_pumped_hydro_mw,
        avg(solar_rooftop_mw) AS oe_solar_rooftop_mw,
        avg(solar_utility_mw) AS oe_solar_utility_mw,
        avg(wind_mw) AS oe_wind_mw,
        avg(total_generation_mw) AS oe_total_generation_mw,
        avg(total_renewable_mw) AS oe_total_renewable_mw
    FROM staging.openelectricity_mix
    GROUP BY 1, 2
),
weather AS (
    SELECT
        time_bucket(INTERVAL '30 minutes', ts) AS bucket_ts,
        CASE station_id
            WHEN '009225' THEN 'WEM'
            WHEN '023034' THEN 'SA1'
            WHEN '040913' THEN 'QLD1'
            WHEN '066037' THEN 'NSW1'
            WHEN '086282' THEN 'VIC1'
            WHEN '094029' THEN 'TAS1'
        END AS region,
        avg(temp_c) AS temp_c,
        avg(apparent_temp_c) AS apparent_temp_c,
        avg(dew_point_c) AS dew_point_c,
        avg(humidity_pct) AS humidity_pct,
        avg(wind_speed_kmh) AS wind_speed_kmh,
        avg(wind_direction_deg) AS wind_direction_deg,
        avg(wind_gust_kmh) AS wind_gust_kmh,
        avg(pressure_hpa) AS pressure_hpa,
        avg(rain_since_9am_mm) AS rain_since_9am_mm,
        avg(cloud_oktas) AS cloud_oktas
    FROM staging.bom_observations
    GROUP BY 1, 2
),
buckets AS (
    SELECT bucket_ts FROM aemo_demand
    UNION
    SELECT bucket_ts FROM oe_mix
),
regions AS (
    SELECT unnest($regions) AS region
),
grid AS (
    SELECT b.bucket_ts, r.region FROM buckets b CROSS JOIN regions r
),
holidays AS (
    SELECT DISTINCT date, region, holiday_name, is_workday
    FROM staging.aemo_holidays
)
SELECT
    grid.bucket_ts,
    grid.region,
    aemo_demand.aemo_demand_mw,
    aemo_demand.aemo_price_mwh,
    aemo_demand.aemo_coal_mw,
    aemo_demand.aemo_gas_mw,
    aemo_demand.aemo_hydro_mw,
    aemo_demand.aemo_wind_mw,
    aemo_demand.aemo_solar_utility_mw,
    aemo_demand.aemo_solar_rooftop_mw,
    aemo_demand.aemo_battery_mw,
    aemo_demand.aemo_net_import_mw,
    aemo_demand.aemo_diesel_mw,
    aemo_demand.aemo_biomass_mw,
    aemo_demand.aemo_total_generation_mw,
    oe_mix.oe_demand_mw,
    oe_mix.oe_price_mwh,
    oe_mix.oe_intensity_kg_per_mwh,
    oe_mix.oe_battery_discharge_mw,
    oe_mix.oe_battery_charge_mw,
    oe_mix.oe_biomass_mw,
    oe_mix.oe_coal_mw,
    oe_mix.oe_distillate_mw,
    oe_mix.oe_gas_mw,
    oe_mix.oe_hydro_mw,
    oe_mix.oe_pumped_hydro_mw,
    oe_mix.oe_solar_rooftop_mw,
    oe_mix.oe_solar_utility_mw,
    oe_mix.oe_wind_mw,
    oe_mix.oe_total_generation_mw,
    oe_mix.oe_total_renewable_mw,
    weather.temp_c,
    weather.apparent_temp_c,
    weather.dew_point_c,
    weather.humidity_pct,
    weather.wind_speed_kmh,
    weather.wind_direction_deg,
    weather.wind_gust_kmh,
    weather.pressure_hpa,
    weather.rain_since_9am_mm,
    weather.cloud_oktas,
    holidays.holiday_name,
    holidays.is_workday,
    (holidays.holiday_name IS NOT NULL) AS is_holiday
FROM grid
LEFT JOIN aemo_demand
    ON aemo_demand.bucket_ts = grid.bucket_ts AND aemo_demand.region = grid.region
LEFT JOIN oe_mix
    ON oe_mix.bucket_ts = grid.bucket_ts AND oe_mix.region = grid.region
ASOF LEFT JOIN weather
    ON weather.region = grid.region AND weather.bucket_ts <= grid.bucket_ts
LEFT JOIN holidays
    ON holidays.date = CAST(grid.bucket_ts AS DATE) AND holidays.region = grid.region
ORDER BY grid.bucket_ts, grid.region
"""

_VERIFY_SQL = """
SELECT
    count(*) AS rows,
    count(DISTINCT (bucket_ts, region)) AS distinct_keys,
    CAST(min(bucket_ts) AS VARCHAR) AS min_ts,
    CAST(max(bucket_ts) AS VARCHAR) AS max_ts,
    count(*) FILTER (WHERE aemo_demand_mw IS NULL AND oe_demand_mw IS NULL) AS rows_with_no_demand,
    count(*) FILTER (WHERE temp_c IS NULL) AS rows_with_no_weather
FROM master
"""


def _training_dir() -> Path:
    settings = get_settings()
    return Path(settings.duckdb_staging_dir).parent / "training"


def master_path() -> Path:
    return _training_dir() / "master.duckdb"


def build_master_table() -> None:
    source_path = staging_path()
    if not source_path.exists():
        raise click.ClickException(f"staging file not found: {source_path}")

    out_path = master_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(out_path))
    try:
        con.execute("SET TimeZone='UTC'")
        # Attached read-only so a concurrent ingest run holding the
        # single read-write lock on `landed.duckdb` can't block this --
        # `master` itself is written into `out_path`'s own default db,
        # `staging.*`-qualified table references below just read from
        # the attached file.
        con.execute(f"ATTACH '{source_path}' AS staging (READ_ONLY)")
        con.execute(_BUILD_SQL, {"regions": _REGIONS})
    finally:
        con.close()


@click.command()
def main() -> None:
    """Build `data/training/master.duckdb`'s `master` table from the shared staging file."""
    configure_logging()
    build_master_table()

    con = duckdb.connect(str(master_path()), read_only=True)
    try:
        row = con.execute(_VERIFY_SQL).fetchone()
    finally:
        con.close()

    assert row is not None
    rows, distinct_keys, min_ts, max_ts, no_demand, no_weather = row
    click.echo(f"master: {rows} rows ({min_ts} .. {max_ts})")
    click.echo(
        f"  distinct (bucket_ts, region) keys: {distinct_keys} (dupes: {rows - distinct_keys})"
    )
    click.echo(
        f"  rows with no demand signal at all: {no_demand} ({no_demand / rows:.1%})"
    )
    click.echo(
        f"  rows with no weather:              {no_weather} ({no_weather / rows:.1%})"
    )
    log.info(
        "build_master_table.done", rows=rows, min_ts=str(min_ts), max_ts=str(max_ts)
    )


if __name__ == "__main__":
    main()
