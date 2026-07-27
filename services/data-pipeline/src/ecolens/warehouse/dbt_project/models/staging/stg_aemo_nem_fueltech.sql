{{ config(materialized="view", tags=["staging", "energy", "nem"]) }}

-- Thin pass-through over raw.aemo_nem_dispatch, keeping ONLY the
-- network-level "NEM" row -- the complement of stg_aemo_nem_dispatch,
-- which keeps the per-region market rows and discards this one.
--
-- AEMO NEM never attributes the fuel-tech generation mix to individual
-- regions in our ingestion fetcher (see
-- ingestion/sources/aemo_nem/engine.py's module docstring) -- it's
-- only ever reported at the whole-network level. int_energy_unified_30min
-- broadcasts this one row per ts onto all 5 NEM sub-regions; it needs
-- its own staging model (rather than living inside
-- stg_aemo_nem_dispatch) because that broadcast is a join, not a rename.

with source as (
    select * from {{ source("raw", "aemo_nem_dispatch") }}
),

renamed as (
    select
        {{ stg_energy_columns() }}
    from source
    where ts is not null
      and region = 'NEM'
)

select * from renamed
