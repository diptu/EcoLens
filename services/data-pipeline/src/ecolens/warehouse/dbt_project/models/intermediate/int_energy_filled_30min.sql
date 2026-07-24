{{
    config(
        materialized="table",
        tags=["intermediate", "energy", "weather", "ml_features"],
        pre_hook="SET LOCAL work_mem = '64MB'",
    )
}}

-- Turns int_energy_with_weather into a *uniform*, gap-free, NULL-free
-- 30-min series per region -- the one place in the warehouse that
-- resolves missing dispatch intervals and missing weather readings, so
-- nothing downstream (ml_features_demand_v1, and ultimately the LSTM's
-- DataLoader) has to resample a ragged calendar or mask a NaN tensor.
--
-- int_energy_with_weather only has a row where a source actually
-- reported -- if AEMO drops a 30-min slot, that slot simply doesn't
-- exist, which silently corrupts anything computed with LAG()/AVG()
-- OVER (ORDER BY ts_30): the "1-step-back" lag quietly becomes a
-- 2-step-back lag. This model builds a full (region x 30-min slot)
-- spine first, then fills every metric with LOCF ("last observation
-- carried forward"; see the `_island` trick below), falling back to
-- the region's all-time average for the rare case of a gap at the very
-- start of a region's history where there's nothing to carry forward.
--
-- Only `data_quality_status = 'final'` energy rows seed the fill
-- (matches ml_features_demand_v1's original filter) -- a still-
-- preliminary AEMO reading is treated the same as a missing one and
-- carried forward until the final settlement figure lands. Every
-- filled row is flagged via `is_gap_filled` / `data_quality_status =
-- 'imputed'` so consumers can weight or inspect it without having to
-- rediscover which rows are real.
--
-- Materialized as a full table, not incremental: LOCF is a
-- whole-series computation per region, so an incremental delete+insert
-- over a lookback window would risk seeding the fill from a partial
-- view of history at the window boundary. This stays cheap because it
-- depends on int_energy_with_weather, which is already incrementally
-- maintained and small -- the same tradeoff ml_features_demand_v1
-- already makes one layer up.

with bounds as (
    select
        min(ts_30) as min_ts_30,
        max(ts_30) as max_ts_30
    from {{ ref("int_energy_with_weather") }}
),

spine as (
    select
        r.region,
        gs.ts_30
    from {{ ref("dim_region") }} r
    cross join bounds b
    cross join generate_series(b.min_ts_30, b.max_ts_30, interval '30 minutes') as gs (ts_30)
),

energy_final as (
    select * from {{ ref("int_energy_with_weather") }}
    where data_quality_status = 'final'
),

holiday as (
    select distinct region, date
    from {{ ref("stg_public_holidays") }}
),

joined as (
    select
        s.region,
        s.ts_30,
        {% for col in ml_fill_columns() %}
        e.{{ col }},
        {% endfor %}
        (h.date is not null) as is_holiday,
        coalesce(e.data_quality_status, 'imputed') as data_quality_status,
        (e.region is null) as is_gap_filled
    from spine s
    left join energy_final e
        on e.region = s.region
        and e.ts_30 = s.ts_30
    left join holiday h
        on h.region = s.region
        and h.date = (s.ts_30 at time zone {{ region_timezone_case("s.region") }})::date
),

-- Stage 1: for each fill column, count non-null values seen so far
-- (per region, ordered by time) -- this is constant within a run of
-- consecutive nulls and increments exactly at each real observation,
-- so it's a ready-made "island id" for that run.
islands as (
    select
        *,
        {% for col in ml_fill_columns() %}
        count({{ col }}) over (
            partition by region order by ts_30
            rows unbounded preceding
        ) as {{ col }}_island
        {{ "," if not loop.last }}
        {% endfor %}
    from joined
),

-- Stage 2: within each island, first_value() picks up the one real
-- observation the island started with -- that's the forward-fill.
-- Leading nulls (no real observation yet at all, island 0) fall
-- through to the region's overall average; if a region has *never*
-- reported a column at all (e.g. a newly onboarded region with no
-- history yet), that average is itself NULL, so it falls through
-- again to the all-region average, and finally to a hard `0` so a
-- NULL genuinely cannot reach ml_features_demand_v1 no matter how
-- sparse the source data is. Both fallbacks are covered by the
-- `is_gap_filled` flag either way.
filled as (
    select
        region,
        ts_30,
        is_holiday,
        is_gap_filled,
        data_quality_status,
        {% for col in ml_fill_columns() %}
        coalesce(
            first_value({{ col }}) over (
                partition by region, {{ col }}_island order by ts_30
            ),
            avg({{ col }}) over (partition by region),
            avg({{ col }}) over (),
            0
        ) as {{ col }}{{ "," if not loop.last }}
        {% endfor %}
    from islands
)

select * from filled
