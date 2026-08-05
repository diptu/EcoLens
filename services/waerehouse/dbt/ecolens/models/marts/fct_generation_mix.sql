-- Hourly generation + emissions by fuel type, per region -- the
-- per-fuel detail int_carbon_intensity computes (via int_fuel_emissions)
-- and then sums away before fct_carbon_intensity. Backs forecast-api's
-- `GET /v1/generation-mix` and the Executive Dashboard's "Emissions by
-- Source" donut, which needs a real per-fuel breakdown, not just a
-- NEM-wide total. Table-materialized (dbt_project.yml).

with detail as (
    select * from {{ ref('int_fuel_emissions') }}
)

select
    date_trunc('hour', ts) as hour,
    network_code,
    region,
    fuel_type,
    sum(generation_mwh) as total_generation_mwh,
    sum(emissions_kgco2e) as total_emissions_kgco2e,
    max(factors_version) as factors_version
from detail
group by date_trunc('hour', ts), network_code, region, fuel_type
