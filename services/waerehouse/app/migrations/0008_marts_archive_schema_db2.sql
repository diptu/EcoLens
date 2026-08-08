-- 0008_marts_archive_schema_db2.sql — targets the SECOND database
-- (Settings.raw_marts_database_url / RAW_MARTS_DATABASE_URL, the
-- ep-noisy-water Neon project), NOT the primary DATABASE_URL. Run this
-- one against RAW_MARTS_DATABASE_URL, not the usual migration target.
--
-- Real physical split for root TODO.md's "save raw and raw.marts in
-- seperate database uing seperate Database_URL (so taht i can save
-- 2*512 mb data)": `raw.*` stays on the primary NeonDB project, bounded
-- by its existing 60-day rolling retention (app/retention/pruning.py).
-- `raw_marts.*` (dbt's marts layer, `+schema: marts` -> dbt's default
-- `<profile_schema>_<custom_schema>` naming -> "raw_marts") is
-- documented ("curated tables retain the complete historical dataset",
-- dbt_project.yml's own comment) to keep growing forever -- 120MB after
-- one year at this project's current data volumes (measured
-- 2026-08-09), the single largest schema in the primary database. This
-- schema is that permanent, unbounded archive; the primary database
-- keeps only a rolling window of the same tables for live queries
-- (app/retention/marts_archive.py).
--
-- Column lists/types copied 1:1 from the real `raw_marts.*` tables on
-- the primary database (introspected live, not guessed) via
-- information_schema.columns. Unlike the dbt-materialized originals
-- (which have no PRIMARY KEY at all -- confirmed live), these DO get a
-- real PRIMARY KEY on each mart's natural key, matching the grain each
-- mart is actually built at (per postgres_loader.py's docstring, the
-- same "ts + region/station/fuel_type" natural-key convention `raw.*`
-- already uses) -- `archive_and_prune_marts_task` relies on
-- `ON CONFLICT DO NOTHING` for retry-safety, since a crash between the
-- copy-to-DB2 step and the delete-from-DB1 step would otherwise
-- reprocess the same still-present DB1 rows.

CREATE SCHEMA IF NOT EXISTS raw_marts;

CREATE TABLE IF NOT EXISTS raw_marts.dim_facility (
    network_code text NOT NULL,
    region       text NOT NULL,
    grain        text,
    region_name  text,
    PRIMARY KEY (network_code, region)
);

CREATE TABLE IF NOT EXISTS raw_marts.dim_energy_mix (
    fuel_type                 text NOT NULL,
    factors_version           text NOT NULL,
    intensity_kgco2e_per_mwh  numeric,
    factor_source             text,
    notes                     text,
    is_renewable              boolean,
    category                  text,
    PRIMARY KEY (fuel_type, factors_version)
);

CREATE TABLE IF NOT EXISTS raw_marts.fct_carbon_intensity (
    hour                                      timestamptz NOT NULL,
    network_code                              text        NOT NULL,
    region                                    text        NOT NULL,
    total_generation_mwh                      numeric,
    total_emissions_kgco2e                    numeric,
    intensity_kgco2e_per_mwh                  numeric,
    factors_version                           text,
    provider_generation_mwh                   numeric,
    provider_emissions_kgco2e                 numeric,
    live_provider_intensity_kgco2e_per_mwh    numeric,
    is_anomalous                              boolean,
    anomaly_score                             numeric,
    anomaly_reason                            text,
    PRIMARY KEY (hour, network_code, region)
);
CREATE INDEX IF NOT EXISTS ix_fct_carbon_intensity_hour ON raw_marts.fct_carbon_intensity (hour);

CREATE TABLE IF NOT EXISTS raw_marts.fct_emissions_5min (
    ts                          timestamptz NOT NULL,
    network_code                text        NOT NULL,
    region                      text        NOT NULL,
    total_generation_mwh        numeric,
    total_emissions_kgco2e      numeric,
    intensity_kgco2e_per_mwh    numeric,
    factors_version             text,
    provider_generation_mwh     numeric,
    provider_emissions_kgco2e   numeric,
    is_anomalous                boolean,
    anomaly_score                numeric,
    anomaly_reason              text,
    PRIMARY KEY (ts, network_code, region)
);
CREATE INDEX IF NOT EXISTS ix_fct_emissions_5min_ts ON raw_marts.fct_emissions_5min (ts);

CREATE TABLE IF NOT EXISTS raw_marts.fct_energy_demand (
    ts                    timestamptz NOT NULL,
    region                text        NOT NULL,
    demand_mw             numeric,
    price_mwh             numeric,
    total_generation_mw   numeric,
    total_renewable_mw    numeric,
    renewable_mw_source   text,
    coal_mw               numeric,
    gas_mw                numeric,
    wind_mw               numeric,
    solar_mw              numeric,
    other_mw              numeric,
    temp_c                numeric,
    apparent_temp_c       numeric,
    humidity_pct          numeric,
    wind_speed_kmh        numeric,
    wind_gust_kmh         numeric,
    wind_direction_deg    numeric,
    cloud_oktas           numeric,
    hour                  numeric,
    dow                   numeric,
    lag_1d                numeric,
    lag_7d                numeric,
    roll_7d               numeric,
    is_anomalous          boolean,
    anomaly_score         numeric,
    anomaly_reason        text,
    PRIMARY KEY (ts, region)
);
CREATE INDEX IF NOT EXISTS ix_fct_energy_demand_ts ON raw_marts.fct_energy_demand (ts);

CREATE TABLE IF NOT EXISTS raw_marts.fct_generation_mix (
    hour                       timestamptz NOT NULL,
    network_code               text        NOT NULL,
    region                     text        NOT NULL,
    fuel_type                  text        NOT NULL,
    total_generation_mwh       numeric,
    total_emissions_kgco2e     numeric,
    factors_version            text,
    is_anomalous                boolean,
    anomaly_score               numeric,
    anomaly_reason             text,
    PRIMARY KEY (hour, network_code, region, fuel_type)
);
CREATE INDEX IF NOT EXISTS ix_fct_generation_mix_hour ON raw_marts.fct_generation_mix (hour);
