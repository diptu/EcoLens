-- Hourly generation + emissions by fuel type, per region -- the
-- per-fuel detail int_carbon_intensity computes (via int_fuel_emissions)
-- and then sums away before fct_carbon_intensity. Backs forecast-api's
-- `GET /v1/generation-mix` and the Executive Dashboard's "Emissions by
-- Source" donut, which needs a real per-fuel breakdown, not just a
-- NEM-wide total.
--
-- Incremental, not `table` -- see `fct_carbon_intensity.sql`'s header
-- for why and for the same "2-day overlap re-aggregates a partially-
-- populated hour wholesale" reasoning (`TODO.md` Phase 1).
--
-- is_anomalous/anomaly_score/anomaly_reason (`TODO.md` Phase 3) -- see
-- `fct_energy_demand.sql`'s header for why. A flagged openelectricity_mix
-- reading for an hour applies to that whole mix reading, not one fuel in
-- isolation, so every fuel_type row for that (hour, network_code, region)
-- shares the same flag -- not fuel-type-specific.

{{
    config(
        materialized='incremental',
        unique_key=['hour', 'network_code', 'region', 'fuel_type'],
        incremental_strategy='delete+insert',
    )
}}

with detail as (
    select * from {{ ref('int_fuel_emissions') }}
    {% if is_incremental() %}
    where ts > (select coalesce(max(hour), '1900-01-01'::timestamptz) from {{ this }}) - interval '2 days'
    {% endif %}
),

aggregated as (
    select
        date_trunc('hour', ts) as hour,
        network_code,
        region,
        fuel_type,
        sum(generation_mwh) as total_generation_mwh,
        sum(emissions_kgco2e) as total_emissions_kgco2e,
        max(factors_version) as factors_version
    from detail
    group by date_trunc('hour', ts), network_code, region, fuel_type
),

anomalies as (
    select * from {{ ref('int_anomaly_by_mix') }}
)

select
    g.*,
    a.anomaly_score is not null as is_anomalous,
    a.anomaly_score,
    a.anomaly_reason
from aggregated g
left join anomalies a
    on g.hour = a.hour and g.network_code = a.network_code and g.region = a.region
