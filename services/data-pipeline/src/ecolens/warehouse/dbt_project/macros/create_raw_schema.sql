{% macro create_raw_schema() %}
{#
  Bootstraps the `raw.*` landing tables described in
  ingestion/INGESTION.md so this dbt project can be built and tested
  before the MongoDB -> PostgreSQL syncer exists. Every statement is
  idempotent (IF NOT EXISTS) -- safe to run against an environment
  where the real syncer already owns these tables, since it never
  drops or alters anything.

  Column contract mirrors each source's OUTPUT_COLUMNS list in
  ecolens.ingestion.sources.*.schema -- keep in sync if those change.
#}
{% if execute %}
{% set ddl %}
create schema if not exists raw;

create table if not exists raw.aemo_nem_dispatch (
    ts timestamptz not null,
    network_code text,
    region text not null,
    data_quality_status text,
    schema_version text,
    demand_mw double precision,
    price_mwh double precision,
    market_value double precision,
    coal_black_mw double precision,
    coal_brown_mw double precision,
    gas_ccgt_mw double precision,
    gas_ocgt_mw double precision,
    gas_other_mw double precision,
    hydro_mw double precision,
    pumped_hydro_mw double precision,
    wind_mw double precision,
    solar_utility_mw double precision,
    solar_rooftop_mw double precision,
    biomass_mw double precision,
    distillate_mw double precision,
    battery_discharge_mw double precision,
    battery_charge_mw double precision,
    curtailment_solar_utility_mw double precision,
    curtailment_wind_mw double precision,
    total_generation_mw double precision,
    renewable_proportion double precision,
    emissions_intensity_kgco2e_per_mwh double precision,
    interconnector_imports_mw double precision,
    interconnector_exports_mw double precision,
    net_import_mw double precision,
    source text,
    ingest_run_id text,
    fetched_at timestamptz,
    unique (region, ts)
);

-- WEM/OpenElectricity share aemo_nem_dispatch's columns but NOT its
-- unique key (see MongoSettings.unique_key_for_source): WEM has one
-- zone so it's keyed on (ts) alone; OpenElectricity is network-level,
-- keyed on (network_code, ts). "including defaults" deliberately skips
-- "including indexes", which would otherwise copy NEM's (region, ts)
-- unique constraint verbatim -- wrong key, and `ON CONFLICT (ts)` /
-- `ON CONFLICT (network_code, ts)` upserts would fail to match it.
create table if not exists raw.aemo_wem_dispatch (
    like raw.aemo_nem_dispatch including defaults,
    unique (ts)
);

create table if not exists raw.openelectricity_responses (
    like raw.aemo_nem_dispatch including defaults,
    unique (network_code, ts)
);

create table if not exists raw.bom_observations (
    ts timestamptz not null,
    region text not null,
    station_id text not null,
    station_name text,
    schema_version text,
    temp_c double precision,
    apparent_temp_c double precision,
    dew_point_c double precision,
    humidity_pct double precision,
    wind_speed_kmh double precision,
    wind_direction_deg double precision,
    wind_gust_kmh double precision,
    pressure_hpa double precision,
    rain_since_9am_mm double precision,
    rain_last_hour_mm double precision,
    cloud_oktas double precision,
    cloud_cover_pct double precision,
    data_quality_status text,
    source text,
    ingest_run_id text,
    fetched_at timestamptz,
    unique (station_id, ts)
);

create table if not exists raw.aemo_holidays (
    date date not null,
    region text not null,
    state text,
    holiday_name text,
    holiday_type text,
    schema_version text,
    is_business_day boolean,
    is_observed boolean,
    observed_date date,
    days_until integer,
    source text,
    ingest_run_id text,
    fetched_at timestamptz,
    unique (region, date)
);
{% endset %}
{% do run_query(ddl) %}
{{ log("create_raw_schema: raw.* bootstrap tables ensured", info=true) }}
{% endif %}
{% endmacro %}
