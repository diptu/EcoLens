-- Per-(ts, network_code, region) carbon intensity: each fuel's MW
-- converted to MWh over its reporting interval (5-min NEM, 30-min WEM --
-- task.md's cadence table), weighted by ecoLens's own
-- seeds/emissions_factors.csv. This is README's "live_mix_weighted"
-- method -- deliberately not the same number as
-- stg_openelectricity_mix.intensity_kg_per_mwh (OpenElectricity's own
-- reported figure, the "live_provider" method, joined in separately
-- below) or a static NGER lookup (the "static_nger" method) -- see
-- README's Emissions model section for why the platform keeps all
-- three instead of trusting one.
--
-- `todo-model-training.md` Phase 7: `provider_generation_mwh`/
-- `provider_emissions_kgco2e` below are OpenElectricity's own reported
-- `total_generation_mw` and `intensity_kg_per_mwh` (NOT ecoLens's
-- per-fuel-weighted figures above -- kept genuinely independent so the
-- two methods can actually be cross-checked against each other, not
-- silently sharing a denominator), converted to the same MWh basis via
-- the same `interval_hours` int_fuel_emissions already uses, so
-- fct_carbon_intensity can generation-weight them up to an hourly
-- figure the same honest way it already does for `live_mix_weighted`.
--
-- Ephemeral (dbt_project.yml) -- inlined into fct_emissions_5min and
-- fct_carbon_intensity, never materialized on its own.
--
-- The per-fuel weighting math itself lives in int_fuel_emissions (also
-- ephemeral) -- fct_generation_mix reads that same model without the
-- fuel_type sum this one applies, so the two marts never disagree on
-- what a fuel's weighted emissions are.

with detail as (
    select * from {{ ref('int_fuel_emissions') }}
),

provider as (
    select
        ts,
        network_code,
        region,
        total_generation_mw
            * (case network_code when 'NEM' then 5.0 / 60 when 'WEM' then 30.0 / 60 else 30.0 / 60 end)
            as provider_generation_mwh,
        total_generation_mw
            * (case network_code when 'NEM' then 5.0 / 60 when 'WEM' then 30.0 / 60 else 30.0 / 60 end)
            * intensity_kg_per_mwh
            as provider_emissions_kgco2e
    from {{ ref('stg_openelectricity_mix') }}
    where intensity_kg_per_mwh is not null and total_generation_mw is not null
)

select
    d.ts,
    d.network_code,
    d.region,
    sum(d.generation_mwh) as total_generation_mwh,
    sum(d.emissions_kgco2e) as total_emissions_kgco2e,
    case
        when sum(d.generation_mwh) is null or sum(d.generation_mwh) = 0 then null
        else sum(d.emissions_kgco2e) / sum(d.generation_mwh)
    end as intensity_kgco2e_per_mwh,
    max(d.factors_version) as factors_version,
    max(p.provider_generation_mwh) as provider_generation_mwh,
    max(p.provider_emissions_kgco2e) as provider_emissions_kgco2e
from detail d
left join provider p
    on d.ts = p.ts and d.network_code = p.network_code and d.region = p.region
group by d.ts, d.network_code, d.region
