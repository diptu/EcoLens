-- Singular test: fails if it returns any rows. `assert_generation_
-- buckets_within_total.sql` already catches the sum *exceeding* the
-- total (double-counted fuel); this catches the other direction --
-- the 5 buckets (coal/gas/wind/solar/other) coming in suspiciously far
-- *under* `total_generation_mw`, which would mean an entire fuel type
-- silently stopped landing in one of them (`other_mw` is a real
-- catch-all -- hydro + biomass + distillate + pumped_hydro +
-- battery_discharge -- not just the 4 named buckets, so a healthy row
-- should sum to close to 100% of the total, not just "most of it").
--
-- Tolerance is the larger of 10% of the total or 50 MW (not exact
-- equality) -- kept as a floor, not tightened to 0, even though
-- `total_generation_mw` is in fact `sum(_FUEL_COLUMNS)` in our own raw
-- ingestion (`ingest_openelectricity.py`'s `total_generation_mw` line,
-- confirmed live 2026-08-10 -- an earlier version of this comment
-- wrongly assumed it was OpenElectricity's own independently-reported
-- figure, which is what let `other_mw` silently exclude
-- `battery_charge_mw` for a while and fail this test on ~8,425 real
-- rows; see `int_demand_with_weather.sql`'s own comment for the fix).
-- A tolerance still earns its keep here: real per-row NULL-coalescing
-- differences between how this model's "as-of" join resolves a missing
-- fuel reading vs. how the raw ingestion's own sum handled it at
-- write-time can still legitimately differ by a little.

select
    ts,
    region,
    coal_mw,
    gas_mw,
    wind_mw,
    solar_mw,
    other_mw,
    total_generation_mw,
    (coalesce(coal_mw, 0) + coalesce(gas_mw, 0) + coalesce(wind_mw, 0)
        + coalesce(solar_mw, 0) + coalesce(other_mw, 0)) as bucket_sum_mw
from {{ ref('int_demand_with_weather') }}
where total_generation_mw is not null
  and total_generation_mw > 0
  and (coalesce(coal_mw, 0) + coalesce(gas_mw, 0) + coalesce(wind_mw, 0)
        + coalesce(solar_mw, 0) + coalesce(other_mw, 0))
      < total_generation_mw - greatest(total_generation_mw * 0.10, 50)
