-- Worst (highest anomaly_score, most-recently-detected on a tie) flagged
-- anomaly per (ts, region), scoped to the 2 demand-table sources
-- (aemo_nem_dispatch/aemo_wem_dispatch) -- what fct_energy_demand.sql
-- joins against. A (ts, region) can have more than one meta.anomalies row
-- if overlapping ingestion runs (e.g. backfill re-covering a window)
-- flagged the same record twice; "worst signal wins" here matches the
-- same rule services/ingestion's own detector already applies when a
-- single row trips more than one signal (anomaly.py's `_Winner`).
--
-- Ephemeral (dbt_project.yml) -- inlined into fct_energy_demand, never
-- materialized on its own.

with ranked as (
    select
        ts,
        region,
        anomaly_score,
        anomaly_reason,
        row_number() over (
            partition by ts, region
            order by anomaly_score desc, detected_at desc
        ) as rn
    from {{ ref('stg_anomalies') }}
    where table_name in ('aemo_nem_dispatch', 'aemo_wem_dispatch')
      and ts is not null
      and region is not null
)

select ts, region, anomaly_score, anomaly_reason
from ranked
where rn = 1
