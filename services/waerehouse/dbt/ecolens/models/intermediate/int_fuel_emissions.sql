-- Per-(ts, network_code, region, fuel_type) generation + emissions --
-- each fuel's MW converted to MWh over its reporting interval (5-min
-- NEM, 30-min WEM), weighted by seeds/emissions_factors.csv. This is
-- the same per-fuel math int_carbon_intensity used to compute inline
-- before summing fuel_type away; factored out here so
-- int_carbon_intensity (sums it) and fct_generation_mix (keeps it) both
-- read it from one place instead of duplicating the weighting logic.
--
-- Ephemeral (dbt_project.yml) -- inlined into whichever mart/intermediate
-- model references it, never materialized on its own.

with mix_share as (
    select * from {{ ref('int_mix_share') }}
),

with_interval as (
    select
        *,
        case network_code
            when 'NEM' then 5.0 / 60
            when 'WEM' then 30.0 / 60
            else 30.0 / 60
        end as interval_hours
    from mix_share
)

select
    w.ts,
    w.network_code,
    w.region,
    w.fuel_type,
    w.generation_mw * w.interval_hours as generation_mwh,
    w.generation_mw * w.interval_hours * coalesce(f.intensity_kgco2e_per_mwh, 0)
        as emissions_kgco2e,
    f.factors_version
from with_interval w
left join {{ ref('emissions_factors') }} f
    on w.fuel_type = f.fuel_type
