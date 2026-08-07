-- Singular test: fails if it returns any rows. Sanity bound on
-- stg_openelectricity_mix's total_renewable_mw (TODO.md Phase 2, model's
-- own header comment) -- whether provider-reported or derived from the
-- per-fuel mix, renewable generation can never exceed total generation
-- for the same (ts, network_code, region). A violation here means either
-- the provider's own figure is inconsistent (real upstream data issue,
-- worth surfacing) or the derived-sum fallback double-counted something.

select ts, network_code, region, total_renewable_mw, total_generation_mw
from {{ ref('stg_openelectricity_mix') }}
where total_renewable_mw is not null
  and total_generation_mw is not null
  and total_renewable_mw > total_generation_mw
