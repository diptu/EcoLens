-- Region/network dimension, standing in for a true per-generator
-- "facility" table.
--
-- Scoping note (be honest about what this actually is): none of the 5
-- ingestion sources report at individual-generator granularity — AEMO
-- NEM/WEM dispatch and OpenElectricity's mix are both *regional
-- aggregates* (docs/data/ingestion-schema.md), not per-power-station
-- readings. NGER's real "facility" concept (a specific generator,
-- reporting its own Scope 1 emissions under the NGER Act) would need a
-- source this platform doesn't ingest — AEMO's NEM Registration and
-- Exemption List or the Clean Energy Regulator's facility-level NGER
-- data. Rather than fabricate facility-level rows this platform has no
-- real data behind, this mart is one row per (network_code, region) —
-- the finest granularity actually available — clearly labelled as such
-- via `grain`. Table-materialized (dbt_project.yml).

select distinct
    network_code,
    region,
    'region' as grain,
    case region
        when 'NSW1' then 'New South Wales'
        when 'QLD1' then 'Queensland'
        when 'VIC1' then 'Victoria'
        when 'SA1' then 'South Australia'
        when 'TAS1' then 'Tasmania'
        when 'WEM' then 'Western Australia (SWIS)'
        else region
    end as region_name
from {{ ref('stg_openelectricity_mix') }}
