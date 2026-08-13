-- models/intermediate/int_demand_with_weather.sql
--
-- README.md's own documented example, adapted to the schema that
-- actually exists: `raw.bom_observations` has no `radiation_mj_m2`
-- column (docs/data/ingestion-schema.md) -- swapped for `humidity_pct`
-- + `cloud_oktas`, the closest real sky-condition proxies BoM's feed
-- gives us. Also widened from NEM-only to NEM+WEM (union both demand
-- sources first) so all 6 regions get the same lag/rolling features,
-- not just the 5 NEM ones -- README's version only showed NEM because
-- that's what fit in a short example, not because WEM shouldn't have it.
--
-- `apparent_temp_c`/`wind_speed_kmh` (from BoM) and `total_generation_mw`/
-- `total_renewable_mw` (from OpenElectricity) were added alongside the
-- ml/features.py `build_features` (ECO-D31) input contract, which needs
-- all four -- the original version above only carried what README's short
-- example used.
--
-- coal_mw/gas_mw/wind_mw/solar_mw/other_mw (added for the multi-task
-- forecast model's generation head, `services/forecast-api/notebooks/
-- lstm.ipynb`'s `EnergyForecastLSTM` -- 4 named buckets + 1 catch-all,
-- not the full dim_energy_mix taxonomy, a deliberate scope decision).
-- `stg_openelectricity_mix` already has `coal_mw`/`gas_mw`/`wind_mw` as
-- single columns (raw ingestion already collapsed OE's fine-grained
-- fueltechs, e.g. coal_black/coal_brown, gas_ccgt/gas_ocgt/gas_steam/
-- gas_recip/gas_wcmg, into these during `_pivot_long_to_wide`) -- only
-- solar (utility + rooftop) and "other" (hydro + biomass + distillate +
-- pumped_hydro + battery_discharge + battery_charge -- everything real
-- generation that isn't one of the 4 named buckets) need summing here.
-- Matters for regions like SA1 (zero coal) and TAS1 (~100% hydro, per
-- services/ingestion/TODO.md's live-verified per-region averages) --
-- without an "other" catch-all, reconciling generation to demand would
-- silently smear their real hydro/storage share across coal/gas/wind/
-- solar, which don't represent it.
--
-- `battery_charge_mw` IS included here (fixed 2026-08-10, was
-- previously excluded on the assumption it's "negative, load not
-- generation" -- real, confirmed wrong: `ingest_openelectricity.py`'s
-- `_FUEL_COLUMNS` stores it as a positive magnitude, and
-- `total_generation_mw` immediately below is ITSELF `sum(_FUEL_COLUMNS)`
-- in our own raw ingestion, `battery_charge_mw` included -- not an
-- independently-reported OpenElectricity figure the way the two
-- `assert_generation_mix_sums_near_total`/comments here previously
-- assumed. Excluding it from "other" while `total_generation_mw`
-- included it made every row with real battery-charging activity fail
-- that reconciliation test by exactly the charging amount -- a
-- persistent, deterministic gap (confirmed live: 8,425 real rows
-- failing on every `dbt build` attempt since at least 2026-08-10
-- 06:30, silently skipping `fct_energy_demand`'s rebuild every time),
-- not the "minor provider-side rounding" the test's own comment
-- assumed. This bucket is a demand-forecast feature, not the carbon/
-- emissions pipeline (that's `int_fuel_emissions`/`fct_carbon_intensity`,
-- untouched by this), so folding charging load into it here doesn't
-- affect any real emissions number shown anywhere in this platform.
--
-- Same nullability contract as total_renewable_mw immediately below:
-- null only when total_generation_mw itself is null (no mix data for
-- that row at all), 0-substituted per missing individual fuel reading
-- otherwise -- not a fabricated 0 when the whole row has no data.
--
-- wind_gust_kmh/wind_direction_deg (added alongside the generation
-- buckets above): `stg_bom_observations` already carries these (thin
-- passthrough), just not previously selected here. Added because the
-- multi-task model's real, executed feature selection (`services/
-- ingestion/scripts/select_features.py`'s output,
-- `data/training/selected_features.json`) found both genuinely
-- important -- dropping them silently instead of adding the 2 columns
-- would mean ignoring a real, data-driven finding for engineering
-- convenience.
--
-- Incremental (dbt_project.yml's `+schema: intermediate` /
-- `raw_intermediate`), NOT ephemeral -- this used to be ephemeral (the
-- `intermediate/` folder default), which meant every one of this
-- model's 6 downstream references (2 singular tests, 4 generic column
-- tests) re-executed this entire query -- LATERAL as-of joins + a
-- 336-row rolling window over the *full unbounded history* -- from
-- scratch, independently. Confirmed live: the top 5 slowest steps in a
-- real build were all reads of this one ephemeral model, summing to
-- ~7,400s out of a ~2,300s-total 90-step build. `delete+insert` on
-- `unique_key=[ts, region]` (same convention the 4 fct_* marts already
-- use) plus the two `is_incremental()` filters below fix this: computed
-- once per build, not 6+ times, and bounded to a small recent window
-- regardless of how much raw history has accumulated.
--
-- Weather and generation-mix joins are both "as-of" (last observation
-- at or before `d.ts`), not exact-timestamp -- BoM/OpenElectricity both
-- report on their own independent cadences that don't line up exactly
-- with AEMO's 5-min dispatch timestamps (confirmed against real data:
-- exact-match joins left ~83% of rows NULL for weather and produced
-- runs of complete rows too short to cover `ml/data.py`'s
-- lookback+horizon=96-step sliding windows even after fixing weather
-- alone -- see TODO.md's Model Operations section). Both change slowly
-- enough that forward-filling the most recent real reading is the
-- standard, honest way to handle this, not a fabricated value.

{{
    config(
        materialized='incremental',
        unique_key=['ts', 'region'],
        incremental_strategy='delete+insert',
    )
}}

with demand_all as (
    select ts, region, demand_mw, price_mwh from {{ ref('stg_aemo_nem_dispatch') }}
    union all
    select ts, region, demand_mw, price_mwh from {{ ref('stg_aemo_wem_dispatch') }}
),

-- Priming buffer for the lag(...,336)/roll_7d window functions below --
-- 336 rows needs 7 full days of *prior* context at WEM's 30-min grain
-- (the binding constraint; NEM's 5-min grain needs far less for the
-- same row count). 12 days = that 7-day requirement + ~40% margin +
-- the 2-day output-retention window itself, so this stays small and
-- flat regardless of total raw history -- not a fixed cost that grows
-- forever the way the old unbounded scan did.
demand as (
    select * from demand_all
    {% if is_incremental() %}
    where ts > (select coalesce(max(ts), '1900-01-01'::timestamptz) from {{ this }}) - interval '12 days'
    {% endif %}
),

weather as (
    select
        ts,
        region,
        temp_c,
        apparent_temp_c,
        humidity_pct,
        wind_speed_kmh,
        wind_gust_kmh,
        wind_direction_deg,
        cloud_oktas
    from {{ ref('stg_bom_observations') }}
),

generation as (
    select
        ts,
        region,
        total_generation_mw,
        total_renewable_mw,
        renewable_mw_source,
        coal_mw,
        gas_mw,
        wind_mw,
        case
            when total_generation_mw is null then null
            else coalesce(solar_utility_mw, 0) + coalesce(solar_rooftop_mw, 0)
        end as solar_mw,
        case
            when total_generation_mw is null then null
            else
                coalesce(hydro_mw, 0)
                + coalesce(biomass_mw, 0)
                + coalesce(distillate_mw, 0)
                + coalesce(pumped_hydro_mw, 0)
                + coalesce(battery_discharge_mw, 0)
                + coalesce(battery_charge_mw, 0)
        end as other_mw
    from {{ ref('stg_openelectricity_mix') }}
)

select
    d.ts,
    d.region,
    d.demand_mw,
    d.price_mwh,
    g.total_generation_mw,
    g.total_renewable_mw,
    -- 'provider' / 'derived' / null -- stg_openelectricity_mix.sql's own
    -- header comment (TODO.md Phase 2's renewable-share fallback).
    -- Surfaced here so downstream consumers (dashboard, forecast-api)
    -- can tell which rows used the derived fallback instead of the
    -- provider's own reported figure -- previously only visible by
    -- querying raw_staging.stg_openelectricity_mix directly.
    g.renewable_mw_source,
    g.coal_mw,
    g.gas_mw,
    g.wind_mw,
    g.solar_mw,
    g.other_mw,
    w.temp_c,
    w.apparent_temp_c,
    w.humidity_pct,
    w.wind_speed_kmh,
    w.wind_gust_kmh,
    w.wind_direction_deg,
    w.cloud_oktas,
    extract(hour from d.ts) as hour,
    extract(dow from d.ts) as dow,
    lag(d.demand_mw, 48) over (partition by d.region order by d.ts) as lag_1d,
    lag(d.demand_mw, 336) over (partition by d.region order by d.ts) as lag_7d,
    avg(d.demand_mw) over (
        partition by d.region order by d.ts rows between 335 preceding and current row
    ) as roll_7d
from demand d
left join lateral (
    select
        w2.temp_c,
        w2.apparent_temp_c,
        w2.humidity_pct,
        w2.wind_speed_kmh,
        w2.wind_gust_kmh,
        w2.wind_direction_deg,
        w2.cloud_oktas
    from weather w2
    where w2.region = d.region and w2.ts <= d.ts
    order by w2.ts desc
    limit 1
) w on true
left join lateral (
    select
        g2.total_generation_mw,
        g2.total_renewable_mw,
        g2.renewable_mw_source,
        g2.coal_mw,
        g2.gas_mw,
        g2.wind_mw,
        g2.solar_mw,
        g2.other_mw
    from generation g2
    where g2.region = d.region and g2.ts <= d.ts
    order by g2.ts desc
    limit 1
) g on true
{% if is_incremental() %}
-- `backfill_lookback_days` (default 2, matching the prior hardcoded
-- window) -- a `dbt build --vars '{backfill_lookback_days: N}'` widens
-- this one run's re-processed trailing window so a real historical
-- backfill's newly-landed `raw.*` rows (older than the normal 2-day
-- trailing window) actually reach this mart, without a `--full-refresh`
-- (which would drop this model's own accumulated history older than
-- `raw.*`'s 60-day retention -- see this file's own header comment).
where d.ts > (select coalesce(max(ts), '1900-01-01'::timestamptz) from {{ this }}) - interval '{{ var("backfill_lookback_days", 2) }} days'
{% endif %}
