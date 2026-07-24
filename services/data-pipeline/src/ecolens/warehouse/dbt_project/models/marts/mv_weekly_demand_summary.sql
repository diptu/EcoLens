{{
    config(
        materialized="materialized_view",
        indexes=[{"columns": ["week_start", "region"], "unique": true}],
        tags=["marts", "aggregate"],
    )
}}

-- Weekly demand summary per region (week starting Monday, local calendar).

select
    date_trunc('week', ts_30 at time zone {{ region_timezone_case("region") }})::date as week_start,
    region,
    sum(demand_mw) * 0.5 as total_demand_mwh,
    avg(demand_mw) as avg_demand_mw,
    max(demand_mw) as peak_demand_mw,
    avg(renewable_proportion) as avg_renewable_proportion
from {{ ref("fact_demand_30min") }}
group by 1, 2
