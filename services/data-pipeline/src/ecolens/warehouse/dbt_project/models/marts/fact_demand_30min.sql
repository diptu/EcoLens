{{ config(materialized="table", tags=["marts", "fact"]) }}

-- The main mart: "at this time, in this region, demand was X and
-- temperature was Y." Demand, generation mix, weather and the holiday
-- flag all live on this one wide table -- the dashboard and
-- forecast-api read from here and never touch MongoDB or raw.*
-- directly (see werehouse.md).

select
    ts_30 as ts,
    ts_30,
    region,
    demand_mw,
    price_mwh,
    market_value,
    coal_black_mw,
    coal_brown_mw,
    gas_ccgt_mw,
    gas_ocgt_mw,
    gas_other_mw,
    hydro_mw,
    pumped_hydro_mw,
    wind_mw,
    solar_utility_mw,
    solar_rooftop_mw,
    biomass_mw,
    distillate_mw,
    battery_discharge_mw,
    battery_charge_mw,
    curtailment_solar_utility_mw,
    curtailment_wind_mw,
    total_generation_mw,
    (
        coalesce(hydro_mw, 0)
        + coalesce(wind_mw, 0)
        + coalesce(solar_utility_mw, 0)
        + coalesce(solar_rooftop_mw, 0)
        + coalesce(biomass_mw, 0)
    ) as renewable_generation_mw,
    renewable_proportion,
    emissions_intensity_kgco2e_per_mwh,
    interconnector_imports_mw,
    interconnector_exports_mw,
    net_import_mw,
    temp_c,
    apparent_temp_c,
    dew_point_c,
    humidity_pct,
    wind_speed_kmh,
    wind_direction_deg,
    wind_gust_kmh,
    pressure_hpa,
    rain_since_9am_mm,
    cloud_cover_pct,
    is_holiday::int as is_holiday,
    data_quality_status
from {{ ref("int_energy_with_weather") }}
