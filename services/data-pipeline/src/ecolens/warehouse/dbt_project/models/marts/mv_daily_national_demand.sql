{{
    config(
        materialized="materialized_view",
        indexes=[{"columns": ["date_local", "region"], "unique": true}],
        tags=["marts", "aggregate"],
    )
}}

-- One row per day per region. Refreshed by dbt on build, and again by
-- the warehouse runner's aggregate-refresh stage
-- (ecolens.warehouse.runner.aggregates) so the dashboard's daily
-- summary endpoint never recomputes this from the 30-min fact table.

select
    (ts_30 at time zone {{ region_timezone_case("region") }})::date as date_local,
    region,
    sum(demand_mw) * 0.5 as total_demand_mwh,
    avg(demand_mw) as avg_demand_mw,
    max(demand_mw) as peak_demand_mw,
    avg(temp_c) as avg_temp_c,
    max(temp_c) as max_temp_c
from {{ ref("fact_demand_30min") }}
group by 1, 2
