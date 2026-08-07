-- One row per flagged record from meta.anomalies, with ts/region/
-- network_code extracted out of the jsonb row_snapshot -- that table has
-- no first-class ts/region columns of its own (services/ingestion writes
-- the flagged record's entire original row as a snapshot instead, since
-- the shape differs per source table; see _sources.yml's meta.anomalies
-- description).
--
-- Scoped to the 3 raw.* tables that actually have a usable (ts, region)
-- shape for downstream marts to join on: aemo_nem_dispatch/
-- aemo_wem_dispatch (demand) and openelectricity_mix (generation mix).
-- bom_observations keys on station_id, not region, directly; aemo_holidays
-- has no ts at all (annual snapshot) -- anomalies against those 2 sources
-- still exist in meta.anomalies, just aren't surfaced through this
-- particular ts+region join (TODO.md Phase 3).

select
    id,
    run_id,
    source,
    table_name,
    (row_snapshot ->> 'ts')::timestamptz as ts,
    row_snapshot ->> 'region' as region,
    row_snapshot ->> 'network_code' as network_code,
    anomaly_score,
    anomaly_reason,
    metric,
    value,
    z_score,
    rule_based_score,
    statistical_score,
    ml_score,
    detected_at
from {{ source('meta', 'anomalies') }}
where table_name in ('aemo_nem_dispatch', 'aemo_wem_dispatch', 'openelectricity_mix')
