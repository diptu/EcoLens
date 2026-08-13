-- Singular test: fails if it returns any rows. Sanity bound on
-- int_demand_with_weather's 5 generation buckets (coal/gas/wind/solar/
-- other, added for the multi-task forecast model's generation head) --
-- their sum can never exceed total_generation_mw for the same (ts,
-- region). Not asserted as exact equality: total_generation_mw is
-- OpenElectricity's own independently-reported total, not derived by
-- summing these buckets in this codebase, so minor provider-side
-- rounding/timing differences aren't necessarily a bug -- but the sum
-- exceeding the total (beyond a small float-rounding tolerance) would
-- mean a fuel got double-counted across two buckets, a real bug worth
-- catching. Mirrors assert_renewable_mw_within_total.sql's same
-- within-total-bound pattern.

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
  and (coalesce(coal_mw, 0) + coalesce(gas_mw, 0) + coalesce(wind_mw, 0)
        + coalesce(solar_mw, 0) + coalesce(other_mw, 0))
      > total_generation_mw + 0.01
