-- 0022_drop_unused_schemas.sql — drops `staging`/`intermediate`, two
-- empty schemas `0001_init.sql` created for an original raw -> staging ->
-- intermediate -> analytics medallion layout. The project later pivoted
-- to dbt, whose `generate_schema_name` macro (no override in
-- `dbt/ecolens/macros/`) names custom-schema models
-- `<profile_schema>_<custom_schema>` -- `raw_staging`/`raw_marts`, not
-- bare `staging`/`intermediate` -- so these two were never actually used
-- by anything: confirmed via a live warehouse audit (no tables/views in
-- either) and a full-repo grep (no migration, dbt model, or app code
-- references them). `analytics` (also created by `0001_init.sql`, and
-- also unreferenced by any code today) is deliberately left alone here —
-- unlike these two, it holds real historical data (~72K rows across
-- `fact_demand_30min`/`fact_generation_30min`/etc.) that a schema drop
-- would destroy; that's a separate decision, not bundled into this
-- always-safe, no-data-loss cleanup.

DROP SCHEMA IF EXISTS staging;
DROP SCHEMA IF EXISTS intermediate;
