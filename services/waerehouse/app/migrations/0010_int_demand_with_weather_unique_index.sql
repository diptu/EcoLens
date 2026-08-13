-- 0010_int_demand_with_weather_unique_index.sql — part 2 of the dbt
-- build speed fix (part 1 is 0009).
--
-- Must run AFTER `int_demand_with_weather` has been built at least once
-- under its new `materialized='incremental'` config (0009 was applied,
-- then a `POST /v1/dbt/build` was run) — this relation didn't exist at
-- all before that (it used to be `ephemeral`, i.e. never materialized).
-- Confirmed live: `raw_intermediate.int_demand_with_weather` now exists
-- with 72,205 rows (dbt.log, "48 of 91 OK created sql incremental model
-- raw_intermediate.int_demand_with_weather [SELECT 72205 in 1496.58s]").
--
-- Same reasoning as the 4 `fct_*` unique indexes in 0009: this model is
-- `incremental_strategy='delete+insert'` on `unique_key=['ts','region']`,
-- so it needs a real unique index backing that key for the DELETE step
-- to use an index scan instead of a sequential scan on every future run.

CREATE UNIQUE INDEX IF NOT EXISTS ux_int_demand_with_weather_ts_region
    ON raw_intermediate.int_demand_with_weather (ts, region);
