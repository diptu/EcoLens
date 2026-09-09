-- Per-(ts, network_code, region, fuel_type) generation + emissions --
-- each fuel's MW converted to MWh over its reporting interval (5-min
-- for both NEM and WEM -- real bug, confirmed live 2026-08-15: WEM was
-- hardcoded to 30-min here, a stale assumption from before WEM's own
-- post-Oct-2023-reform move to 5-min dispatch. Both the real AEMO WEM
-- connector (`ingest_aemo_wem.py`'s own docstring: "every real 5-min
-- interval is kept") and OpenElectricity's own WEM feed (confirmed live
-- via `fetch_network_data('WEM', ...)`, consecutive timestamps 5 min
-- apart) are genuinely 5-min now -- the 30-min assumption inflated
-- every WEM generation/emissions figure in this pipeline 6x
-- (0.5h / (5/60)h), weighted by seeds/emissions_factors.csv. This is
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
            when 'WEM' then 5.0 / 60
            else 5.0 / 60
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
