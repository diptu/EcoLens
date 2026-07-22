{{ config(materialized="view", tags=["staging", "weather"]) }}

-- Thin pass-through over raw.bom_observations: rename/cast only.

with source as (
    select * from {{ source("raw", "bom_observations") }}
),

renamed as (
    select
        ts::timestamptz as ts,
        region,
        station_id,
        station_name,
        schema_version,
        temp_c::double precision as temp_c,
        apparent_temp_c::double precision as apparent_temp_c,
        dew_point_c::double precision as dew_point_c,
        humidity_pct::double precision as humidity_pct,
        wind_speed_kmh::double precision as wind_speed_kmh,
        wind_direction_deg::double precision as wind_direction_deg,
        wind_gust_kmh::double precision as wind_gust_kmh,
        pressure_hpa::double precision as pressure_hpa,
        rain_since_9am_mm::double precision as rain_since_9am_mm,
        rain_last_hour_mm::double precision as rain_last_hour_mm,
        cloud_oktas::double precision as cloud_oktas,
        cloud_cover_pct::double precision as cloud_cover_pct,
        lower(data_quality_status) as data_quality_status,
        source,
        ingest_run_id,
        fetched_at::timestamptz as fetched_at
    from source
    where ts is not null
      and region is not null
)

select * from renamed
