-- 5-minute NEM dispatch, per region. Thin passthrough over raw.aemo_nem_dispatch
-- (docs/data/ingestion-schema.md) -- staging models don't transform, they
-- just rename/typecast/expose a stable interface intermediate models build on.

select
    ts,
    region,
    demand_mw,
    price_mwh,
    coal_mw,
    gas_mw,
    hydro_mw,
    wind_mw,
    solar_utility_mw,
    solar_rooftop_mw,
    battery_mw,
    net_import_mw,
    source,
    ingested_at,
    ingest_run_id
from {{ source('raw', 'aemo_nem_dispatch') }}
