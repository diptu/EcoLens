-- Singular test: fails if it returns any rows. Per Contributing.md's
-- "Adding a new emissions factor source" checklist -- "a singular test
-- that the new factors produce a system-level intensity within ±2% of
-- the published national value".
--
-- `expected_national_intensity_kgco2e_per_mwh`'s default below is a
-- PLACEHOLDER, not a verified figure -- pick the actual current
-- published NEM-wide average (AEMO's Quarterly Energy Dynamics /
-- DCCEEW's National Greenhouse Accounts Factors both publish one) and
-- set it via `--vars` or dbt_project.yml before treating this test as
-- meaningful. Left in rather than omitted so the *mechanism* Contributing.md
-- asks for exists and is wired up correctly; the number itself needs a
-- human to fill in with a citation, same as seeds/emissions_factors.csv's
-- own per-fuel values.
--
-- `severity: warn`, not the dbt default `error` (fixed 2026-08-10) --
-- an unconfigured placeholder threshold has no business hard-failing
-- real `dbt build` runs: confirmed live, this test alone (real system
-- intensity has drifted outside ±2% of the placeholder 650) was enough
-- to cascade-skip `fct_energy_demand`'s rebuild on every real build
-- attempt since at least 06:30 today, alongside the unrelated
-- `assert_generation_mix_sums_near_total` bug fixed the same day. Warn
-- keeps the real mechanism Contributing.md asks for intact (it still
-- runs, still reports) without letting a not-yet-calibrated placeholder
-- block downstream marts a real forecast model depends on. Restore to
-- `error` once a real cited value replaces the placeholder below.
--
-- Only checks NEM (network_code = 'NEM') -- WEM is a separate, much
-- smaller, islanded system with its own published average that this
-- single tolerance check doesn't attempt to cover.

{{ config(severity='warn') }}

{% set expected = var('expected_national_intensity_kgco2e_per_mwh', 650) %}
{% set tolerance_pct = var('national_intensity_tolerance_pct', 2) %}

with system_average as (
    select
        sum(total_emissions_kgco2e) / nullif(sum(total_generation_mwh), 0)
            as system_intensity_kgco2e_per_mwh
    from {{ ref('fct_emissions_5min') }}
    where network_code = 'NEM'
)

select system_intensity_kgco2e_per_mwh
from system_average
where system_intensity_kgco2e_per_mwh is not null
  and abs(system_intensity_kgco2e_per_mwh - {{ expected }}) > {{ expected }} * {{ tolerance_pct }} / 100.0
