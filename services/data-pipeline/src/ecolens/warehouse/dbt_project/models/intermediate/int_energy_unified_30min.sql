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
-- OpenElectricity is network-level, not per-region, so it's excluded
-- here -- see stg_openelectricity_network for that series.
--
-- Incremental with a lookback window (default 5 days, see
-- dbt_project.yml's `lookback_days` var) to pick up AEMO's
-- late-arriving/revised settlement data without reprocessing all of
-- history every run.

with nem as (
    select * from {{ ref("stg_aemo_nem_dispatch") }}
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

nem_30min as (
    select
        region,
        {{ bucket_30min("ts") }} as ts_30,
        {% for col in energy_metric_columns() %}
        avg({{ col }}) as {{ col }},
        {% endfor %}
        max(data_quality_status) as data_quality_status,
        max(source) as source
    from nem
    group by region, {{ bucket_30min("ts") }}
),

wem_30min as (
    select
        region,
        {{ bucket_30min("ts") }} as ts_30,
        {% for col in energy_metric_columns() %}
        avg({{ col }}) as {{ col }},
        {% endfor %}
        max(data_quality_status) as data_quality_status,
        max(source) as source
    from wem
    group by region, {{ bucket_30min("ts") }}
),

unioned as (
    select * from nem_30min
    union all
    select * from wem_30min
)

select * from unioned
