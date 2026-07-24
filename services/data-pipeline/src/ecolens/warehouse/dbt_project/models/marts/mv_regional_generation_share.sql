{{
    config(
        materialized="materialized_view",
        indexes=[{"columns": ["date_local", "region"], "unique": true}],
        tags=["marts", "aggregate"],
    )
}}

-- Renewable proportion per day per region.

select
    (ts_30 at time zone {{ region_timezone_case("region") }})::date as date_local,
    region,
    avg(renewable_proportion) as avg_renewable_proportion,
    sum(renewable_generation_mw) * 0.5 as renewable_energy_mwh,
    sum(total_generation_mw) * 0.5 as total_energy_mwh,
    avg(emissions_intensity_kgco2e_per_mwh) as avg_emissions_intensity_kgco2e_per_mwh
from {{ ref("fact_generation_30min") }}
group by 1, 2
