{{ config(materialized="view", tags=["staging", "holidays"]) }}

-- Thin pass-through over raw.aemo_holidays: rename/cast only.

with source as (
    select * from {{ source("raw", "aemo_holidays") }}
),

renamed as (
    select
        date::date as date,
        region,
        state,
        holiday_name,
        holiday_type,
        schema_version,
        coalesce(is_business_day, false) as is_business_day,
        coalesce(is_observed, false) as is_observed,
        observed_date::date as observed_date,
        source,
        ingest_run_id,
        fetched_at::timestamptz as fetched_at
    from source
    where date is not null
      and region is not null
)

select * from renamed
