-- Hourly, generation-weighted carbon intensity per region — distinct
-- from fct_emissions_5min's row-level detail: this is the "time-weighted
-- average intensity" README's Emissions model section describes the
-- footprint calculator using, pre-aggregated so `/v1/footprint` doesn't
-- have to re-weight raw 5-/30-min rows on every request. Table-materialized
-- (dbt_project.yml).
--
-- `todo-model-training.md` Phase 7: `live_provider_intensity_kgco2e_per_mwh`
-- is OpenElectricity's own reported intensity (via int_carbon_intensity's
-- `provider_*` columns), generation-weighted up to the hour the same
-- honest way `intensity_kgco2e_per_mwh` (the `live_mix_weighted` method)
-- already is -- `null` for an hour where the provider had no real data,
-- not a fabricated fallback value (forecast-api's own COALESCE decides
-- what to actually serve when this is null, not this mart).
--
-- Incremental, not `table` — `fct_energy_demand.sql`'s header explains
-- why (`TODO.md` Phase 1). The `is_incremental()` filter runs on
-- `detail`'s row-level `ts` *before* the hourly `group by` below, using
-- `2 days` of overlap so an hour that was only partially populated as
-- of the previous run gets its aggregate fully recomputed (not just
-- rows strictly newer than the last run's max `ts`) — `delete+insert`
-- on `unique_key=hour` then replaces that hour's row wholesale rather
-- than trying to merge partial sums.
--
-- is_anomalous/anomaly_score/anomaly_reason (`TODO.md` "prod grade"
-- pass, extending Phase 3's anomaly-awareness past fct_energy_demand/
-- fct_generation_mix) -- same int_anomaly_by_mix hourly rollup
-- fct_generation_mix already joins, reused here rather than duplicated.

{{
    config(
        materialized='incremental',
        unique_key=['hour', 'network_code', 'region'],
        incremental_strategy='delete+insert',
    )
}}

with detail as (
    select * from {{ ref('int_carbon_intensity') }}
    {% if is_incremental() %}
    where ts > (select coalesce(max(hour), '1900-01-01'::timestamptz) from {{ this }}) - interval '2 days'
    {% endif %}
),

aggregated as (
    select
        date_trunc('hour', ts) as hour,
        network_code,
        region,
        sum(total_generation_mwh) as total_generation_mwh,
        sum(total_emissions_kgco2e) as total_emissions_kgco2e,
        case
            when sum(total_generation_mwh) is null or sum(total_generation_mwh) = 0 then null
            else sum(total_emissions_kgco2e) / sum(total_generation_mwh)
        end as intensity_kgco2e_per_mwh,
        max(factors_version) as factors_version,
        sum(provider_generation_mwh) as provider_generation_mwh,
        sum(provider_emissions_kgco2e) as provider_emissions_kgco2e,
        case
            when sum(provider_generation_mwh) is null or sum(provider_generation_mwh) = 0 then null
            else sum(provider_emissions_kgco2e) / sum(provider_generation_mwh)
        end as live_provider_intensity_kgco2e_per_mwh
    from detail
    group by date_trunc('hour', ts), network_code, region
),

anomalies as (
    select * from {{ ref('int_anomaly_by_mix') }}
)

select
    c.*,
    a.anomaly_score is not null as is_anomalous,
    a.anomaly_score,
    a.anomaly_reason
from aggregated c
left join anomalies a
    on c.hour = a.hour and c.network_code = a.network_code and c.region = a.region
