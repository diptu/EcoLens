{{
    config(
        materialized="table",
        tags=["marts", "ml", "ml_features"],
        pre_hook="SET LOCAL work_mem = '64MB'",
    )
}}

-- Master feature table for the PyTorch LSTM demand model (see
-- services/forecast-api/strategy.md for how a row here gets served to
-- the model at inference time, and forecast-api/src/.../queries.py for
-- the one query that currently reads it). One row per (region, ts_30),
-- built on int_energy_filled_30min so every 30-min slot in a region's
-- history is present and every column below is non-null -- no
-- resampling, gap-filling, or NaN handling needs to happen in the
-- training/serving Python.
--
-- Columns:
--   * demand_mw                    -- the training target
--   * demand_lag_01..demand_lag_48 -- 24h of autoregressive lags
--                                      (30-min grain, matches
--                                      Settings.model_lookback). NULL
--                                      only for the first
--                                      `ml_feature_lags` rows of a
--                                      region's history -- a
--                                      training-set boundary
--                                      condition (no prior slots
--                                      exist to lag from), not a
--                                      data-quality gap. Never NULL at
--                                      inference time, since serving
--                                      always has real lookback.
--   * demand_rolling_avg_7d / demand_rolling_std_7d
--   * price_mwh, renewable_generation_mw, renewable_proportion,
--     emissions_intensity_kgco2e_per_mwh, net_import_mw
--                                   -- market + grid-mix covariates
--   * temp_c, apparent_temp_c, dew_point_c, humidity_pct,
--     wind_speed_kmh, wind_direction_deg, wind_gust_kmh, pressure_hpa,
--     rain_since_9am_mm, cloud_cover_pct
--                                   -- the full 10-column BoM weather set
--   * is_holiday, is_weekend       -- calendar covariates
--   * hour_sin, hour_cos, dow_sin, dow_cos, month_sin, month_cos
--                                   -- cyclical encodings of
--                                      region-local time (a neural net
--                                      has no notion that hour 23 and
--                                      hour 0 are adjacent unless you
--                                      tell it)
--   * is_gap_filled, data_quality_status
--                                   -- audit columns carried through
--                                      from int_energy_filled_30min;
--                                      not model inputs, just so a
--                                      training run can inspect/weight
--                                      imputed rows if it wants to
--
-- Rolling/lag window functions run over int_energy_filled_30min's
-- uniform grid, so "48 rows back" really is 24 hours back -- on the
-- old fact_demand_30min-based version, a missing slot silently shifted
-- every lag by one, and the 7-day rolling window covered more or less
-- than 7 days depending on how many slots were missing.

with base as (
    select * from {{ ref("int_energy_filled_30min") }}
),

local_time as (
    select
        *,
        (ts_30 at time zone {{ region_timezone_case("region") }}) as ts_local
    from base
),

featured as (
    select
        ts_30,
        ts_30 as ts,
        region,
        demand_mw,
        {% for i in range(1, var("ml_feature_lags", 48) + 1) %}
        lag(demand_mw, {{ i }}) over (
            partition by region order by ts_30
        ) as demand_lag_{{ "%02d" | format(i) }},
        {% endfor %}
        avg(demand_mw) over (
            partition by region order by ts_30
            rows between {{ var("ml_rolling_window_slots", 336) }} preceding and 1 preceding
        ) as demand_rolling_avg_7d,
        stddev(demand_mw) over (
            partition by region order by ts_30
            rows between {{ var("ml_rolling_window_slots", 336) }} preceding and 1 preceding
        ) as demand_rolling_std_7d,
        price_mwh,
        (
            coalesce(hydro_mw, 0)
            + coalesce(wind_mw, 0)
            + coalesce(solar_utility_mw, 0)
            + coalesce(solar_rooftop_mw, 0)
            + coalesce(biomass_mw, 0)
        ) as renewable_generation_mw,
        renewable_proportion,
        emissions_intensity_kgco2e_per_mwh,
        net_import_mw,
        temp_c,
        apparent_temp_c,
        dew_point_c,
        humidity_pct,
        wind_speed_kmh,
        wind_direction_deg,
        wind_gust_kmh,
        pressure_hpa,
        rain_since_9am_mm,
        cloud_cover_pct,
        is_holiday::int as is_holiday,
        (extract(isodow from ts_local) in (6, 7))::int as is_weekend,
        sin(radians(360.0 * (extract(hour from ts_local) * 2 + floor(extract(minute from ts_local) / 30)) / 48)) as hour_sin,
        cos(radians(360.0 * (extract(hour from ts_local) * 2 + floor(extract(minute from ts_local) / 30)) / 48)) as hour_cos,
        sin(radians(360.0 * extract(isodow from ts_local) / 7)) as dow_sin,
        cos(radians(360.0 * extract(isodow from ts_local) / 7)) as dow_cos,
        sin(radians(360.0 * extract(month from ts_local) / 12)) as month_sin,
        cos(radians(360.0 * extract(month from ts_local) / 12)) as month_cos,
        is_gap_filled,
        data_quality_status
    from local_time
)

select * from featured
