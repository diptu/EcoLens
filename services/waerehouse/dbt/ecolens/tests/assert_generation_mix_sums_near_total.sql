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
-- equality): `total_generation_mw` is OpenElectricity's own
-- independently-reported figure, not derived by summing these buckets
-- in this codebase, so minor provider-side rounding/timing gaps are
-- expected and not a bug -- this is a sanity floor against a real
-- missing-bucket regression, not a strict reconciliation.

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
