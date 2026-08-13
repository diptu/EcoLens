-- Unpivots stg_openelectricity_mix's wide per-fuel MW columns into one row
-- per (ts, network_code, region, fuel_type), plus each fuel's share of
-- total generation for that interval. `fuel_type` values here have to
-- match seeds/emissions_factors.csv's `fuel_type` column exactly --
-- int_carbon_intensity joins on it.
--
-- Ephemeral (dbt_project.yml) -- inlined into int_carbon_intensity,
-- never materialized on its own.

with mix as (
    select * from {{ ref('stg_openelectricity_mix') }}
),

unpivoted as (
    select ts, network_code, region, 'coal' as fuel_type, coal_mw as generation_mw from mix
    union all
    select ts, network_code, region, 'gas', gas_mw from mix
    union all
    select ts, network_code, region, 'hydro', hydro_mw from mix
    union all
    select ts, network_code, region, 'wind', wind_mw from mix
    union all
    select ts, network_code, region, 'solar_utility', solar_utility_mw from mix
    union all
    select ts, network_code, region, 'solar_rooftop', solar_rooftop_mw from mix
    union all
    select ts, network_code, region, 'battery_discharge', battery_discharge_mw from mix
    union all
    select ts, network_code, region, 'battery_charge', battery_charge_mw from mix
    union all
    select ts, network_code, region, 'pumped_hydro', pumped_hydro_mw from mix
    union all
    select ts, network_code, region, 'biomass', biomass_mw from mix
    union all
    select ts, network_code, region, 'distillate', distillate_mw from mix
)

select
    u.ts,
    u.network_code,
    u.region,
    u.fuel_type,
    u.generation_mw,
    m.total_generation_mw,
    case
        when m.total_generation_mw is null or m.total_generation_mw = 0 then null
        else u.generation_mw / m.total_generation_mw
    end as share_of_total
from unpivoted u
left join mix m
    on u.ts = m.ts and u.network_code = m.network_code and u.region = m.region
where u.generation_mw is not null
