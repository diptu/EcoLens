-- Generation mix, wide form, one row per (ts, network_code, region). Thin
-- passthrough over raw.openelectricity_mix (docs/data/ingestion-schema.md)
-- for every column except total_renewable_mw -- see below.
--
-- overview.md §3 (Carbon Insights): "Where renewable energy metrics are
-- unavailable, the platform derives the renewable proportion from the
-- observed electricity generation mix, ensuring carbon insights remain
-- available even when external data is incomplete." Previously this was a
-- straight passthrough of the provider's own (sometimes-null)
-- total_renewable_mw with no fallback -- `TODO.md` Phase 2.
--
-- The derived sum uses exactly the fuel types `dim_energy_mix.sql` already
-- classifies `is_renewable = true` (hydro, wind, solar_utility,
-- solar_rooftop, biomass) -- deliberately *not* pumped_hydro/
-- battery_discharge, which that model classifies as `storage` (discharged
-- energy of mixed/unknown original generation source, not itself
-- renewable generation). Reusing that existing classification instead of
-- picking a second list here keeps "what counts as renewable" defined in
-- exactly one place.

with base as (
    select
        ts,
        network_code,
        region,
        coal_mw,
        gas_mw,
        hydro_mw,
        wind_mw,
        solar_utility_mw,
        solar_rooftop_mw,
        battery_discharge_mw,
        battery_charge_mw,
        pumped_hydro_mw,
        biomass_mw,
        distillate_mw,
        total_generation_mw,
        total_renewable_mw as provider_renewable_mw,
        demand_mw,
        price_mwh,
        intensity_kg_per_mwh,
        source,
        ingested_at,
        ingest_run_id
    from {{ source('raw', 'openelectricity_mix') }}
)

select
    ts,
    network_code,
    region,
    coal_mw,
    gas_mw,
    hydro_mw,
    wind_mw,
    solar_utility_mw,
    solar_rooftop_mw,
    battery_discharge_mw,
    battery_charge_mw,
    pumped_hydro_mw,
    biomass_mw,
    distillate_mw,
    total_generation_mw,
    coalesce(
        provider_renewable_mw,
        case
            when total_generation_mw is null then null
            else
                coalesce(hydro_mw, 0)
                + coalesce(wind_mw, 0)
                + coalesce(solar_utility_mw, 0)
                + coalesce(solar_rooftop_mw, 0)
                + coalesce(biomass_mw, 0)
        end
    ) as total_renewable_mw,
    case
        when provider_renewable_mw is not null then 'provider'
        when total_generation_mw is not null then 'derived'
        else null
    end as renewable_mw_source,
    demand_mw,
    price_mwh,
    intensity_kg_per_mwh,
    source,
    ingested_at,
    ingest_run_id
from base
