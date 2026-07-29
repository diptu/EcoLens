{{
    config(
        materialized="materialized_view",
        indexes=[{"columns": ["date_local"], "unique": true}],
        tags=["marts", "aggregate"],
    )
}}

-- True national (summed across ALL regions, not per-region) daily
-- demand + emissions actuals -- root TODO.md's Dashboard/Executive
-- Tier 2 finding: mv_daily_national_demand.sql already exists but is
-- grouped by (day, *region*) despite its name, and carries no emissions
-- columns at all. This is the sibling that's actually national and has
-- the real mass-emissions total ("Total CO2e") the Executive trend
-- chart's "Actual" line needs -- neither of those was a query someone
-- forgot to write against an existing column; both needed a real model
-- change.
--
-- "date_local" is bucketed against a single fixed reference timezone
-- (Australia/Brisbane -- always AEST/UTC+10, no DST), not each row's
-- own region-local calendar day the way mv_daily_national_demand does
-- per-region: once regions are summed together there's no longer a
-- single "this row's region" to look up a timezone for, and AEMO's own
-- NEM settlement clock uses this exact fixed-AEST convention for "which
-- day is this" -- a real, documented choice, not an arbitrary one.

with national_30min as (
    select
        ts_30,
        (ts_30 at time zone 'Australia/Brisbane')::date as date_local,
        sum(demand_mw) as demand_mw,
        avg(renewable_proportion) as renewable_proportion,
        avg(emissions_intensity_kgco2e_per_mwh) as emissions_intensity_kgco2e_per_mwh,
        -- Exact regardless of later grouping -- summed here, at the
        -- per-region-row grain, before regions are collapsed away; see
        -- queries.get_national_summary's own docstring for why this
        -- can't be recovered correctly from the post-sum demand_mw
        -- above times an unweighted average intensity.
        sum(demand_mw * 0.5 * emissions_intensity_kgco2e_per_mwh) / 1000.0 as carbon_tco2e
    from {{ ref("fact_demand_30min") }}
    group by ts_30
)

select
    date_local,
    sum(demand_mw) * 0.5 as total_demand_mwh,
    avg(renewable_proportion) as avg_renewable_proportion,
    avg(emissions_intensity_kgco2e_per_mwh) as avg_emissions_intensity_kgco2e_per_mwh,
    sum(carbon_tco2e) as total_carbon_tco2e
from national_30min
group by date_local
