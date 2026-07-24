-- Singular test: (region, ts_30) must be unique in fact_demand_30min --
-- the API's timeseries queries assume one row per region per 30-min
-- slot.

select region, ts_30, count(*) as n
from {{ ref("fact_demand_30min") }}
group by region, ts_30
having count(*) > 1
