-- Demand + weather + lag/rolling features, one row per (ts, region),
-- across both NEM and WEM. This is what forecast-api's training/
-- inference code and the dashboard actually read, so it should be a
-- real table, not recomputed per query.
--
-- Incremental (`delete+insert` on `unique_key`, not `table`) —
-- `raw.*`'s own 60-day retention (app/retention/pruning.py) means a
-- `table` materialization here would silently rebuild this mart from
-- only whatever's left in `raw.*` on every `dbt run`, dropping all
-- older history the mart had already accumulated (`TODO.md` Phase 1).
-- `int_demand_with_weather`'s lag/rolling window functions still see
-- the full history available in `raw.*` on every run (they're computed
-- before the filter below is applied) — only the *materialize* step is
-- incremental, the feature computation itself isn't windowed down.
-- `ts > max(ts) - 2 days` re-processes a short trailing overlap so
-- late-arriving/corrected rows near the previous run's high-water mark
-- still get picked up, not just brand-new timestamps.
--
-- is_anomalous/anomaly_score/anomaly_reason (TODO.md Phase 3): overview.md
-- §1 -- "flags them with an anomaly score and explanation, enabling
-- downstream systems and users to differentiate between data quality
-- issues and real-world grid events". services/ingestion's detector
-- writes meta.anomalies directly (never through raw.*), so without this
-- join a flagged reading looked identical to a clean one everywhere this
-- mart's own consumers (forecast-api, the dashboard) actually read.
-- Left join, never filtered out -- same "preserve the record, just flag
-- it" contract the detector itself uses (anomaly.py's own docstring).

{{
    config(
        materialized='incremental',
        unique_key=['ts', 'region'],
        incremental_strategy='delete+insert',
    )
}}

with base as (
    select * from {{ ref('int_demand_with_weather') }}
),

anomalies as (
    select * from {{ ref('int_anomaly_by_demand') }}
)

select
    b.*,
    a.anomaly_score is not null as is_anomalous,
    a.anomaly_score,
    a.anomaly_reason
from base b
left join anomalies a on b.ts = a.ts and b.region = a.region
{% if is_incremental() %}
where b.ts > (select coalesce(max(ts), '1900-01-01'::timestamptz) from {{ this }}) - interval '2 days'
{% endif %}
