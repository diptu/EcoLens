-- 5-minute WEM (SWIS) dispatch, single region (post-Oct-2023-reform
-- cadence -- see int_fuel_emissions.sql's comment for the real 30-min
-- assumption bug this stale "30-minute" label used to encourage
-- elsewhere in the pipeline, fixed 2026-08-15). Thin passthrough over
-- raw.aemo_wem_dispatch -- WEM's own fuel mix (diesel, no net_import since
-- it's islanded), matching docs/data/ingestion-schema.md.

select
    ts,
    region,
    demand_mw,
    price_mwh,
    coal_mw,
    gas_mw,
    diesel_mw,
    wind_mw,
    solar_utility_mw,
    solar_rooftop_mw,
    battery_mw,
    biomass_mw,
    total_generation_mw,
    source,
    ingested_at,
    ingest_run_id
from {{ source('raw', 'aemo_wem_dispatch') }}
