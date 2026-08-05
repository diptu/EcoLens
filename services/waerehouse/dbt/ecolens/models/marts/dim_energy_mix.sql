-- Fuel-type dimension: one row per fuel, its emissions factor, and a
-- renewable/fossil/storage classification. Built straight from
-- seeds/emissions_factors.csv rather than raw data — this is reference
-- data, not something derived from an ingested source. Table-materialized
-- (dbt_project.yml).

select
    fuel_type,
    intensity_kgco2e_per_mwh,
    factors_version,
    source as factor_source,
    notes,
    case
        when fuel_type in ('hydro', 'wind', 'solar_utility', 'solar_rooftop', 'biomass')
            then true
        else false
    end as is_renewable,
    case
        when fuel_type in ('battery', 'battery_discharge', 'battery_charge', 'pumped_hydro')
            then 'storage'
        when fuel_type = 'net_import'
            then 'interconnector'
        when fuel_type in ('hydro', 'wind', 'solar_utility', 'solar_rooftop', 'biomass')
            then 'renewable'
        else 'fossil'
    end as category
from {{ ref('emissions_factors') }}
