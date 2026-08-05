-- 0001_raw_schema.sql — formally establishes this service's ownership of
-- the `raw.*` schema (README Phase 2's "PostgreSQL Schema Provisioning").
--
-- Idempotent (CREATE IF NOT EXISTS) and matches the shape data-pipeline's
-- own migrations (0002-0006_raw_*.sql) already created in the shared
-- NeonDB instance exactly -- this is not a new/different schema, it's
-- the warehouse service's own copy of the same DDL, safe to (re-)apply
-- against a database that already has these tables (a no-op) or a fresh
-- one (creates them for real). `services/data-pipeline`'s migrations
-- stay the historical record of *how* this schema came to exist; this
-- file is what lets `services/waerehouse` stand up the same schema
-- on its own, without depending on that other service's migration
-- scripts going forward.
--
-- Timestamp indexing for range-based deletions (README Phase 2's other
-- ask): 4 of these 5 tables already have `ts` as the *leading* column of
-- their composite PRIMARY KEY (`ts, region[, fuel_type]` / `ts,
-- station_id`) -- Postgres's own btree PK index already serves a
-- `WHERE ts < ...` range delete efficiently with no extra index needed.
-- `aemo_holidays` is the one exception (`PRIMARY KEY (region,
-- holiday_date)`, `region` leading) -- deliberately not given a
-- `holiday_date` index here: it's a tiny annual snapshot table (~365
-- rows/year across all regions), not a per-source time series, and
-- isn't a real candidate for the 60-day rolling-window retention policy
-- (`retention.pruning`) the other 4 tables are.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.openelectricity_mix (
    ts                                      timestamptz NOT NULL,
    region                                  text        NOT NULL,
    fuel_type                               text        NOT NULL,
    generation_mw                           numeric,
    emissions_intensity_kg_co2e_per_mwh     numeric,
    source_run_id                           uuid,
    ingested_at                             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, region, fuel_type)
);

CREATE TABLE IF NOT EXISTS raw.aemo_nem_dispatch (
    ts             timestamptz NOT NULL,
    region         text        NOT NULL,
    demand_mw      numeric,
    price          numeric,
    source_run_id  uuid,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, region)
);

CREATE TABLE IF NOT EXISTS raw.aemo_wem_dispatch (
    ts             timestamptz NOT NULL,
    region         text        NOT NULL,
    demand_mw      numeric,
    price          numeric,
    source_run_id  uuid,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, region)
);

CREATE TABLE IF NOT EXISTS raw.bom_observations (
    ts               timestamptz NOT NULL,
    station_id       text        NOT NULL,
    region           text        NOT NULL,
    temp_c           numeric,
    humidity_pct     numeric,
    wind_speed_kmh   numeric,
    radiation_mj_m2  numeric,
    source_run_id    uuid,
    ingested_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, station_id)
);

CREATE TABLE IF NOT EXISTS raw.aemo_holidays (
    region        text        NOT NULL,
    holiday_date  date        NOT NULL,
    holiday_name  text        NOT NULL,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (region, holiday_date)
);
