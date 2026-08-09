-- Singular test: fails if it returns any rows. Sanity bound on
-- stg_openelectricity_mix's total_renewable_mw (TODO.md Phase 2, model's
-- own header comment) -- whether provider-reported or derived from the
-- per-fuel mix, renewable generation can never exceed total generation
-- for the same (ts, network_code, region). A violation here means either
-- the provider's own figure is inconsistent (real upstream data issue,
-- worth surfacing) or the derived-sum fallback double-counted something.
--
-- `+ 0.01` (10kW) tolerance -- real production data found 350 real
-- violating rows, every one TAS1 at ~100% renewable (hydro+wind, zero
-- fossil), off by 1e-10 to 1e-4 MW (e.g. 1633.5439000000001 vs
-- 1633.5439). That's IEEE 754 floating-point summation noise from two
-- different summation orders landing on the same value, not a real
-- data inconsistency -- confirmed by the scale (a real provider/derived
-- mismatch would be off by whole MW, not fractions of a watt). This
-- comparison was strict (no tolerance) and was silently failing every
-- real `dbt build` since whenever TAS1 first hit ~100% renewable,
-- which in turn made dbt skip every model downstream of this test
-- (fct_carbon_intensity/fct_generation_mix/fct_emissions_5min all stop
-- getting rebuilt) -- diagnosed 2026-08-09 from the Emissions Trend
-- dashboard chart going stale.
select ts, network_code, region, total_renewable_mw, total_generation_mw
from {{ ref('stg_openelectricity_mix') }}
where total_renewable_mw is not null
  and total_generation_mw is not null
  and total_renewable_mw > total_generation_mw + 0.01
