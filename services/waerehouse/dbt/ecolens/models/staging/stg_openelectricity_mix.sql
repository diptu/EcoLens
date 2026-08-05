-- Generation mix, wide form, one row per (ts, network_code, region). Thin
-- passthrough over raw.openelectricity_mix (docs/data/ingestion-schema.md).

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
    total_renewable_mw,
    demand_mw,
    price_mwh,
    intensity_kg_per_mwh,
    source,
    ingested_at,
    ingest_run_id
from {{ source('raw', 'openelectricity_mix') }}
