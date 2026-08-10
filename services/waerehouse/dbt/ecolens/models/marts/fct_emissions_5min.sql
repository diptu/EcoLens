-- Row-level carbon intensity + emissions, one row per (ts, network_code,
-- region) at OpenElectricity's own reporting cadence (5-min NEM, 30-min
-- WEM — the "5min" in this mart's name is NEM's cadence and the name
-- README documents; WEM rows land here too at their own 30-min cadence,
-- not literally every 5 minutes).
--
-- Incremental, not `table` — see `fct_energy_demand.sql`'s header for
-- why (`TODO.md` Phase 1: `table` + `raw.*`'s 60-day pruning silently
-- drops mart history older than the retention window on every run).
--
-- is_anomalous/anomaly_score/anomaly_reason (`TODO.md` "prod grade"
-- pass, extending Phase 3's anomaly-awareness past fct_energy_demand/
-- fct_generation_mix): row-level, not hourly, via int_anomaly_by_mix_row
-- -- this mart's own grain, unlike fct_carbon_intensity's hourly one.

{{
    config(
        materialized='incremental',
        unique_key=['ts', 'network_code', 'region'],
        incremental_strategy='delete+insert',
    )
}}

with base as (
    select * from {{ ref('int_carbon_intensity') }}
),

anomalies as (
    select * from {{ ref('int_anomaly_by_mix_row') }}
)

select
    b.*,
    a.anomaly_score is not null as is_anomalous,
    a.anomaly_score,
    a.anomaly_reason
from base b
left join anomalies a
    on b.ts = a.ts and b.network_code = a.network_code and b.region = a.region
{% if is_incremental() %}
-- Same `backfill_lookback_days` var as the other marts' own output
-- filters -- `fct_energy_demand.sql`'s header has the full reasoning.
where b.ts > (select coalesce(max(ts), '1900-01-01'::timestamptz) from {{ this }}) - interval '{{ var("backfill_lookback_days", 2) }} days'
{% endif %}
