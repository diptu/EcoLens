-- Worst flagged generation-mix anomaly per (hour, network_code, region) --
-- fct_generation_mix.sql is hourly-aggregated (date_trunc('hour', ts)),
-- so row-level anomalies from openelectricity_mix are rolled up to the
-- same hourly grain before joining, same "worst signal wins" tie-break as
-- int_anomaly_by_demand.sql.
--
-- Ephemeral (dbt_project.yml) -- inlined into fct_generation_mix, never
-- materialized on its own.

with ranked as (
    select
        date_trunc('hour', ts) as hour,
        network_code,
        region,
        anomaly_score,
        anomaly_reason,
        row_number() over (
            partition by date_trunc('hour', ts), network_code, region
            order by anomaly_score desc, detected_at desc
        ) as rn
    from {{ ref('stg_anomalies') }}
    where table_name = 'openelectricity_mix'
      and ts is not null
      and region is not null
)

select hour, network_code, region, anomaly_score, anomaly_reason
from ranked
where rn = 1
