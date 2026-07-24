{{ config(materialized="table", tags=["marts", "dimension"]) }}

select distinct
    date,
    region,
    state,
    holiday_name,
    holiday_type,
    is_observed,
    observed_date
from {{ ref("stg_public_holidays") }}
