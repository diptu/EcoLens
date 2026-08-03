-- Per-(ts, network_code, region) carbon intensity: each fuel's MW
-- converted to MWh over its reporting interval (5-min NEM, 30-min WEM --
-- task.md's cadence table), weighted by ecoLens's own
-- seeds/emissions_factors.csv. This is README's "live_mix_weighted"
-- method -- deliberately not the same number as
-- stg_openelectricity_mix.intensity_kg_per_mwh (OpenElectricity's own
-- reported figure, the "live_provider" method) or a static NGER lookup
-- (the "static_nger" method) -- see README's Emissions model section for
-- why the platform keeps all three instead of trusting one.
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
)

select
    ts,
    network_code,
    region,
    sum(generation_mwh) as total_generation_mwh,
    sum(emissions_kgco2e) as total_emissions_kgco2e,
    case
        when sum(generation_mwh) is null or sum(generation_mwh) = 0 then null
        else sum(emissions_kgco2e) / sum(generation_mwh)
    end as intensity_kgco2e_per_mwh,
    max(factors_version) as factors_version
from detail
group by ts, network_code, region
