{{ config(materialized="view", tags=["staging", "energy", "nem"]) }}

-- Thin pass-through over raw.aemo_nem_dispatch: rename/cast only, no
-- joins, no math. See werehouse.md's staging-layer rules.
--
-- AEMO NEM emits per-region docs (NSW1/QLD1/VIC1/SA1/TAS1) plus one
-- network-level "NEM" aggregate doc per ts (see
-- ingestion/sources/aemo_nem/engine.py's module docstring) -- both are
-- valid raw.aemo_nem_dispatch rows, but this staging model feeds the
-- per-region fact table, so the network aggregate is filtered here,
-- not upstream. stg_openelectricity_network is the network-level series.

with source as (
    select * from {{ source("raw", "aemo_nem_dispatch") }}
),

renamed as (
    select
        {{ stg_energy_columns() }}
    from source
    where ts is not null
      and region in ('NSW1', 'QLD1', 'VIC1', 'SA1', 'TAS1')
)

select * from renamed
