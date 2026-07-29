{{
    config(
        materialized="incremental",
        unique_key=["region", "ts_30"],
        on_schema_change="sync_all_columns",
        incremental_strategy="delete+insert",
        tags=["intermediate", "energy"],
    )
}}

-- Unifies AEMO NEM (5-min) and AEMO WEM (30-min) onto one 30-min grain
-- per region, per werehouse.md's "make the grains match" layer.
--
-- Structural quirk this has to account for: AEMO NEM's per-region rows
-- (NSW1/QLD1/VIC1/SA1/TAS1, stg_aemo_nem_dispatch) only ever populate
-- the *market* columns (demand/price/interconnector flow) -- the
-- fuel-tech generation mix is only ever populated on the network-level
-- "NEM" row (stg_aemo_nem_fueltech), which isn't itself one of the 6
-- regions in dim_region. Left un-broadcast, every NEM sub-region's
-- fuel-mix columns would be NULL all the way down to fact_demand_30min
-- (where renewable_generation_mw is computed via
-- `coalesce(hydro_mw, 0) + ...`, so it would silently read 0 instead of
-- NULL -- a wrong answer, not a visible gap). So nem_fueltech_30min
-- below is broadcast onto all 5 NEM sub-regions by ts_30 alone (no
-- region key on that side of the join).
--
-- OpenElectricity (stg_openelectricity_network) is network-level too --
-- it fills a gap for WEM directly (same region key), and for NEM's
-- broadcast fuel-tech mix, but it CANNOT substitute for a missing
-- NSW1/QLD1/VIC1/SA1/TAS1 *market* row: OpenElectricity never reports
-- NEM below the whole-network level, so there's no equivalent-
-- granularity fallback for per-region demand/price today.
--
-- Incremental with a lookback window (default 5 days, see
-- dbt_project.yml's `lookback_days` var) to pick up AEMO's
-- late-arriving/revised settlement data without reprocessing all of
-- history every run.
--
-- Root TODO.md's "Anomaly Detection" section: `anomaly_score`/
-- `anomaly_flags`/`anomaly_explanation` are per-*record* on the staging
-- models this reads from, but this model buckets several 5-min NEM
-- records into one 30-min row (and, for NEM specifically, further
-- combines the per-region market row with the network-level fueltech
-- row and an OpenElectricity fallback) -- so those three columns need
-- an explicit "how do N contributing anomaly scores become one"
-- decision, not an average (an anomaly score isn't a physical quantity
-- to average; the worst one is the one worth surfacing). Two-step rule,
-- applied consistently at both the intra-bucket (`*_30min` CTEs) and
-- cross-source (`nem_final`/`wem_final`) merges: take the *max* score,
-- and carry the flags/explanation belonging to whichever contributing
-- row/source had that max -- never a blended/averaged explanation
-- string, which would describe a record that doesn't correspond to any
-- one real observation.



with nem_market as (
    select * from {{ ref("stg_aemo_nem_dispatch") }}
    {% if is_incremental() %}
    where ts >= {{ lookback_cutoff() }}
    {% endif %}
),

nem_fueltech as (
    select * from {{ ref("stg_aemo_nem_fueltech") }}
    {% if is_incremental() %}
    where ts >= {{ lookback_cutoff() }}
    {% endif %}
),

wem as (
    select * from {{ ref("stg_aemo_wem_dispatch") }}
    {% if is_incremental() %}
    where ts >= {{ lookback_cutoff() }}
    {% endif %}
),

oe as (
    select * from {{ ref("stg_openelectricity_network") }}
    {% if is_incremental() %}
    where ts >= {{ lookback_cutoff() }}
    {% endif %}
),

nem_market_30min as (
    select
        region,
        {{ bucket_30min("ts") }} as ts_30,
        {% for col in market_metric_columns() %}
        avg({{ col }}) as {{ col }},
        {% endfor %}
        max(data_quality_status) as data_quality_status,
        max(source) as source,
        {{ worst_anomaly_agg() }}
    from nem_market
    group by region, {{ bucket_30min("ts") }}
),

-- One row per ts_30 (no region) -- broadcast onto all 5 NEM
-- sub-regions in nem_final below.
nem_fueltech_30min as (
    select
        {{ bucket_30min("ts") }} as ts_30,
        {% for col in fueltech_metric_columns() %}
        avg({{ col }}) as {{ col }},
        {% endfor %}
        max(source) as source,
        {{ worst_anomaly_agg() }}
    from nem_fueltech
    group by {{ bucket_30min("ts") }}
),

wem_30min as (
    select
        region,
        {{ bucket_30min("ts") }} as ts_30,
        {% for col in energy_metric_columns() %}
        avg({{ col }}) as {{ col }},
        {% endfor %}
        max(data_quality_status) as data_quality_status,
        max(source) as source,
        {{ worst_anomaly_agg() }}
    from wem
    group by region, {{ bucket_30min("ts") }}
),

-- Network-level fallback, keyed by region so 'NEM' broadcasts onto the
-- 5 sub-regions the same way nem_fueltech_30min does, and 'WEM' joins
-- directly onto wem_30min.
oe_30min as (
    select
        region,
        {{ bucket_30min("ts") }} as ts_30,
        {% for col in energy_metric_columns() %}
        avg({{ col }}) as {{ col }},
        {% endfor %}
        max(source) as source,
        {{ worst_anomaly_agg() }}
    from oe
    group by region, {{ bucket_30min("ts") }}
),

nem_final as (
    select
        m.region,
        m.ts_30,
        {% for col in market_metric_columns() %}
        m.{{ col }},
        {% endfor %}
        {% for col in fueltech_metric_columns() %}
        coalesce(f.{{ col }}, oe_nem.{{ col }}) as {{ col }},
        {% endfor %}
        m.data_quality_status,
        m.source,
        {{ pick_worse_of_three("m", "f", "oe_nem") }}
    from nem_market_30min m
    left join nem_fueltech_30min f
        on f.ts_30 = m.ts_30
    left join oe_30min oe_nem
        on oe_nem.region = 'NEM'
        and oe_nem.ts_30 = m.ts_30
),

wem_final as (
    select
        w.region,
        w.ts_30,
        {% for col in energy_metric_columns() %}
        coalesce(w.{{ col }}, oe_wem.{{ col }}) as {{ col }},
        {% endfor %}
        w.data_quality_status,
        w.source,
        {{ pick_worse_of_two("w", "oe_wem") }}
    from wem_30min w
    left join oe_30min oe_wem
        on oe_wem.region = 'WEM'
        and oe_wem.ts_30 = w.ts_30
),

unioned as (
    select * from nem_final
    union all
    select * from wem_final
)

select * from unioned
