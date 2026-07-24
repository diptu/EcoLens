{{ config(materialized="view", tags=["staging", "energy", "wem"]) }}

-- Thin pass-through over raw.aemo_wem_dispatch: rename/cast only.

with source as (
    select * from {{ source("raw", "aemo_wem_dispatch") }}
),

renamed as (
    select
        {{ stg_energy_columns() }}
    from source
    where ts is not null
      and region is not null
)

select * from renamed
