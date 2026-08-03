-- models/intermediate/int_demand_with_weather.sql
--
-- README.md's own documented example, adapted to the schema that
-- actually exists: `raw.bom_observations` has no `radiation_mj_m2`
-- column (docs/data/ingestion-schema.md) -- swapped for `humidity_pct`
-- + `cloud_oktas`, the closest real sky-condition proxies BoM's feed
-- gives us. Also widened from NEM-only to NEM+WEM (union both demand
-- sources first) so all 6 regions get the same lag/rolling features,
-- not just the 5 NEM ones -- README's version only showed NEM because
-- that's what fit in a short example, not because WEM shouldn't have it.
--
-- `apparent_temp_c`/`wind_speed_kmh` (from BoM) and `total_generation_mw`/
-- `total_renewable_mw` (from OpenElectricity) were added alongside the
-- ml/features.py `build_features` (ECO-D31) input contract, which needs
-- all four -- the original version above only carried what README's short
-- example used.
--
-- Ephemeral (dbt_project.yml) -- inlined into fct_energy_demand, never
-- materialized on its own.

with demand as (
    select ts, region, demand_mw, price_mwh from {{ ref('stg_aemo_nem_dispatch') }}
    union all
    select ts, region, demand_mw, price_mwh from {{ ref('stg_aemo_wem_dispatch') }}
),

weather as (
    select * from {{ ref('stg_bom_observations') }}
),

generation as (
    select ts, region, total_generation_mw, total_renewable_mw
    from {{ ref('stg_openelectricity_mix') }}
)

select
    d.ts,
    d.region,
    d.demand_mw,
    d.price_mwh,
    g.total_generation_mw,
    g.total_renewable_mw,
    w.temp_c,
    w.apparent_temp_c,
    w.humidity_pct,
    w.wind_speed_kmh,
    w.cloud_oktas,
    extract(hour from d.ts) as hour,
    extract(dow from d.ts) as dow,
    lag(d.demand_mw, 48) over (partition by d.region order by d.ts) as lag_1d,
    lag(d.demand_mw, 336) over (partition by d.region order by d.ts) as lag_7d,
    avg(d.demand_mw) over (
        partition by d.region order by d.ts rows between 335 preceding and current row
    ) as roll_7d
from demand d
left join weather w
    on d.region = w.region and d.ts = w.ts
left join generation g
    on d.region = g.region and d.ts = g.ts
