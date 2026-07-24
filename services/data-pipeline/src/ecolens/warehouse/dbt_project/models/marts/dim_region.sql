{{ config(materialized="table", tags=["marts", "dimension"]) }}

select
    region,
    state,
    population,
    timezone
from {{ ref("region_reference") }}
order by region
