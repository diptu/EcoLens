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
-- Only checks NEM (network_code = 'NEM') -- WEM is a separate, much
-- smaller, islanded system with its own published average that this
-- single tolerance check doesn't attempt to cover.

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
