-- Weather observations, 6 stations. Thin passthrough over
-- raw.bom_observations (docs/data/ingestion-schema.md).

select
    ts,
    station_id,
    region,
    temp_c,
    apparent_temp_c,
    dew_point_c,
    humidity_pct,
    wind_speed_kmh,
    wind_direction_deg,
    wind_gust_kmh,
    pressure_hpa,
    rain_since_9am_mm,
    cloud_oktas,
    source,
    ingested_at,
    ingest_run_id
from {{ source('raw', 'bom_observations') }}
