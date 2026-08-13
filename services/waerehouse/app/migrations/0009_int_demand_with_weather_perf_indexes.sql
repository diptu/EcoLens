-- 0009_int_demand_with_weather_perf_indexes.sql — dbt build speed fix,
-- part 1 (indexes; part 2 is 0010, which needs int_demand_with_weather
-- to exist as a real table first — see that migration's own header).
--
-- Root cause this fixes: `int_demand_with_weather.sql`'s two `LEFT JOIN
-- LATERAL` "as-of" lookups (`WHERE region = d.region AND ts <= d.ts
-- ORDER BY ts DESC LIMIT 1`, against `raw.bom_observations` and
-- `raw.openelectricity_mix`) had no supporting index anywhere — each
-- table's only index is its PRIMARY KEY, `(ts, ...)`, with `ts` leading
-- rather than `region`, which doesn't serve a "latest row per region"
-- lookup efficiently. Confirmed live: 2 of that model's tests took
-- ~497s each, and 2 related singular tests took ~2250s (37.5 min)
-- each, all re-scanning effectively unindexed. `(region, ts)` lets
-- Postgres turn each LATERAL probe into an index range scan + short
-- backward scan instead.
--
-- `raw.aemo_nem_dispatch`/`raw.aemo_wem_dispatch` aren't LATERAL
-- targets (they only feed the `demand` CTE, already filtered to a
-- small window by `int_demand_with_weather.sql`'s own `is_incremental()`
-- change), so these two are a smaller win — included anyway since the
-- existing PK's `(ts, region)` order doesn't match this access pattern
-- either, and it's cheap.
--
-- The `fct_*` unique indexes below are a separate but related fix:
-- these 4 marts are all `materialized: incremental` with
-- `incremental_strategy: delete+insert` on a declared `unique_key`, but
-- (confirmed live) have no actual unique constraint/index backing that
-- key on this (primary) database — so every incremental run's DELETE
-- step has to scan for matching rows instead of using an index,
-- getting slower as each mart grows (observed: one run inserted a
-- single row into fct_energy_demand in 425s while siblings inserted
-- thousands of rows in ~5s in the same run).
--
-- Pre-flight required before running this against a real database:
-- `CREATE UNIQUE INDEX` fails outright if any duplicate key rows exist.
-- A real duplicate-build race is plausible here (see scheduler.py's
-- `_STALE_LOCK_MINUTES` fix, same change set) — run e.g.
--   SELECT ts, region, count(*) FROM raw_marts.fct_energy_demand
--   GROUP BY ts, region HAVING count(*) > 1;
-- (and the equivalent for the other 3 marts, using their own key
-- columns below) and dedupe any hits before applying this file.

CREATE INDEX IF NOT EXISTS ix_bom_observations_region_ts
    ON raw.bom_observations (region, ts);
CREATE INDEX IF NOT EXISTS ix_openelectricity_mix_region_ts
    ON raw.openelectricity_mix (region, ts);

CREATE INDEX IF NOT EXISTS ix_aemo_nem_dispatch_region_ts
    ON raw.aemo_nem_dispatch (region, ts);
CREATE INDEX IF NOT EXISTS ix_aemo_wem_dispatch_region_ts
    ON raw.aemo_wem_dispatch (region, ts);

CREATE UNIQUE INDEX IF NOT EXISTS ux_fct_energy_demand_ts_region
    ON raw_marts.fct_energy_demand (ts, region);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fct_carbon_intensity_hour_network_region
    ON raw_marts.fct_carbon_intensity (hour, network_code, region);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fct_emissions_5min_ts_network_region
    ON raw_marts.fct_emissions_5min (ts, network_code, region);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fct_generation_mix_hour_network_region_fuel
    ON raw_marts.fct_generation_mix (hour, network_code, region, fuel_type);
