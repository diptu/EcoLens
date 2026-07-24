{{
    config(
        materialized="incremental",
        unique_key=["region", "ts_30"],
        on_schema_change="sync_all_columns",
        incremental_strategy="delete+insert",
        tags=["intermediate", "energy", "weather"],
    )
}}

-- Joins the unified 30-min energy series to BoM weather and the
-- public-holiday calendar. Weather is averaged onto the same 30-min
-- buckets; the holiday flag is resolved against each region's local
-- calendar date, not UTC -- everything upstream stays in UTC and this
-- is the one place we convert, per werehouse.md's DST guidance.

with energy as (
    select * from {{ ref("int_energy_unified_30min") }}
    {% if is_incremental() %}
    where ts_30 >= {{ lookback_cutoff() }}
    {% endif %}
),

weather as (
    select
        region,
        {{ bucket_30min("ts") }} as ts_30,
        avg(temp_c) as temp_c,
        avg(apparent_temp_c) as apparent_temp_c,
        avg(dew_point_c) as dew_point_c,
        avg(humidity_pct) as humidity_pct,
        avg(wind_speed_kmh) as wind_speed_kmh,
        avg(wind_direction_deg) as wind_direction_deg,
        avg(wind_gust_kmh) as wind_gust_kmh,
        avg(pressure_hpa) as pressure_hpa,
        avg(rain_since_9am_mm) as rain_since_9am_mm,
        avg(cloud_cover_pct) as cloud_cover_pct
    from {{ ref("stg_bom_observations") }}
    group by region, {{ bucket_30min("ts") }}
),

holiday as (
    select distinct region, date
    from {{ ref("stg_public_holidays") }}
),

joined as (
    select
        e.region,
        e.ts_30,
        {% for col in energy_metric_columns() %}
        e.{{ col }},
        {% endfor %}
        e.data_quality_status,
        e.source,
        w.temp_c,
        w.apparent_temp_c,
        w.dew_point_c,
        w.humidity_pct,
        w.wind_speed_kmh,
        w.wind_direction_deg,
        w.wind_gust_kmh,
        w.pressure_hpa,
        w.rain_since_9am_mm,
        w.cloud_cover_pct,
        (h.date is not null) as is_holiday
    from energy e
    left join weather w
        on w.region = e.region
        and w.ts_30 = e.ts_30
    left join holiday h
        on h.region = e.region
        and h.date = (e.ts_30 at time zone {{ region_timezone_case("e.region") }})::date
)

select * from joined
