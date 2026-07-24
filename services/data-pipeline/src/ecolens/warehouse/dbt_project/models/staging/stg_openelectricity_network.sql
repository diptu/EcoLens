{{ config(materialized="view", tags=["staging", "energy", "openelectricity"]) }}

-- Thin pass-through over raw.openelectricity_responses: rename/cast
-- only. Network-level (NEM/WEM as a whole), not per-region -- kept as
-- its own staging model for cross-checking rather than blended into
-- int_energy_unified_30min's per-region grain. See werehouse.md.

with source as (
    select * from {{ source("raw", "openelectricity_responses") }}
),

renamed as (
    select
        {{ stg_energy_columns() }}
    from source
    where ts is not null
)

select * from renamed
