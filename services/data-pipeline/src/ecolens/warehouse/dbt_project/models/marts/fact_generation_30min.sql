{{ config(materialized="table", tags=["marts", "fact"]) }}

-- Generation-mix-focused subset of fact_demand_30min. Built on top of
-- (not duplicated from) fact_demand_30min so renewable_generation_mw
-- stays a single source of truth.

select
    ts_30,
    region,
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
    renewable_generation_mw,
    renewable_proportion,
    emissions_intensity_kgco2e_per_mwh,
    interconnector_imports_mw,
    interconnector_exports_mw,
    net_import_mw,
    data_quality_status
from {{ ref("fact_demand_30min") }}
