-- Worst flagged generation-mix anomaly per (ts, network_code, region) --
-- the row-level counterpart of int_anomaly_by_mix.sql (which rolls the
-- same source up to the hour for fct_generation_mix/fct_carbon_intensity).
-- fct_emissions_5min.sql needs row-level, not hourly, since it's the
-- row-level counterpart of fct_carbon_intensity itself (TODO.md "prod
-- grade" pass, extending Phase 3's anomaly-awareness to the 2 marts it
-- didn't originally cover).
--
-- Ephemeral (dbt_project.yml) -- inlined into fct_emissions_5min, never
-- materialized on its own.

with ranked as (
    select
        ts,
        network_code,
        region,
        anomaly_score,
        anomaly_reason,
        row_number() over (
            partition by ts, network_code, region
            order by anomaly_score desc, detected_at desc
        ) as rn
    from {{ ref('stg_anomalies') }}
    where table_name = 'openelectricity_mix'
      and ts is not null
      and region is not null
)

select ts, network_code, region, anomaly_score, anomaly_reason
from ranked
where rn = 1
