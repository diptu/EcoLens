-- Demand + weather + lag/rolling features, one row per (ts, region),
-- across both NEM and WEM. Table-materialized (dbt_project.yml) — this
-- is what forecast-api's training/inference code and the dashboard
-- actually read, so it should be a real table, not recomputed per query.

select * from {{ ref('int_demand_with_weather') }}
