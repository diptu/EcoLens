-- 0002_fix_raw_schema_to_match_real_ingestion_output.sql
--
-- **Real bug found live 2026-08-06** while building this service's own
-- Phase 2 loader: `0001_raw_schema.sql` (and the identical data-pipeline
-- migrations it was copied from) define `raw.*` columns that no longer
-- match what `services/ingestion`'s actual tasks stage in DuckDB today
-- -- confirmed directly via `DESCRIBE` against the real shared staging
-- file, not assumed. Concretely: `aemo_nem_dispatch`/`aemo_wem_dispatch`
-- ingest per-fueltech breakdown columns (`coal_mw`/`gas_mw`/`hydro_mw`/
-- ...) and `price_mwh` (not `price`) that never existed in the original
-- migration; `bom_observations` ingests `apparent_temp_c`/
-- `dew_point_c`/`wind_direction_deg`/`wind_gust_kmh`/`cloud_oktas` the
-- original never had (and never had `radiation_mj_m2`, which the
-- original *did* have -- the real BoM task never populates it);
-- `openelectricity_mix` is landed **wide** (one row per `ts`+`region`,
-- one column per fuel type) but the original schema was designed
-- **long** (`PRIMARY KEY (ts, region, fuel_type)`, a `fuel_type` column
-- that doesn't exist in the real DataFrame at all); `aemo_holidays`
-- ingests `date` (not `holiday_date`) plus `is_workday`, which the
-- original never had.
--
-- Net effect: `loaders.postgres_loader.load_to_postgres`'s `CREATE TEMP
-- TABLE ... (LIKE raw.X INCLUDING DEFAULTS)` + `COPY` would fail
-- outright against every one of these 5 tables as originally defined --
-- confirmed by checking: **every `raw.*` table is completely empty**
-- (`SELECT count(*)` = 0 across all 5), meaning this mismatch has
-- silently broken the entire DuckDB-to-Postgres sync path for every
-- source, from the start, not just for this new service. Safe to
-- `DROP`+`CREATE` rather than `ALTER` given there is zero real data to
-- preserve.
--
-- Also replaces the old ambiguous reuse of `ingested_at` (originally
-- meant "when Postgres loaded this row", but the real DataFrame *also*
-- has its own `ingested_at` meaning "when ingestion fetched this row" --
-- a genuine name collision) with two distinct, unambiguous columns:
-- the DataFrame's own `ingested_at`/`ingest_run_id` (fetch-time
-- provenance, now real columns instead of silently dropped) and a new
-- `loaded_at timestamptz NOT NULL DEFAULT now()` (Postgres-side load
-- time, not populated by `COPY` -- `INCLUDING DEFAULTS` lets it fall
-- back to `now()` the same way the old `source_run_id`/`ingested_at`
-- pair used to).

DROP TABLE IF EXISTS raw.aemo_nem_dispatch;
CREATE TABLE raw.aemo_nem_dispatch (
    ts                timestamptz NOT NULL,
    region            text        NOT NULL,
    demand_mw         numeric,
    price_mwh         numeric,
    coal_mw           numeric,
    gas_mw            numeric,
    hydro_mw          numeric,
    wind_mw           numeric,
    solar_utility_mw  numeric,
    solar_rooftop_mw  numeric,
    battery_mw        numeric,
    net_import_mw     numeric,
    source            text,
    ingested_at       timestamptz,
    ingest_run_id     uuid,
    loaded_at         timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, region)
);

DROP TABLE IF EXISTS raw.aemo_wem_dispatch;
CREATE TABLE raw.aemo_wem_dispatch (
    ts                    timestamptz NOT NULL,
    region                text        NOT NULL,
    demand_mw             numeric,
    price_mwh             numeric,
    coal_mw               numeric,
    gas_mw                numeric,
    diesel_mw             numeric,
    wind_mw               numeric,
    solar_utility_mw      numeric,
    solar_rooftop_mw      numeric,
    battery_mw            numeric,
    biomass_mw            numeric,
    total_generation_mw   numeric,
    source                text,
    ingested_at           timestamptz,
    ingest_run_id         uuid,
    loaded_at             timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, region)
);

DROP TABLE IF EXISTS raw.bom_observations;
CREATE TABLE raw.bom_observations (
    ts                   timestamptz NOT NULL,
    station_id           text        NOT NULL,
    region               text        NOT NULL,
    temp_c               numeric,
    apparent_temp_c      numeric,
    dew_point_c          numeric,
    humidity_pct         numeric,
    wind_speed_kmh       numeric,
    wind_direction_deg   numeric,
    wind_gust_kmh        numeric,
    pressure_hpa         numeric,
    rain_since_9am_mm    numeric,
    cloud_oktas          numeric,
    source               text,
    ingested_at          timestamptz,
    ingest_run_id        uuid,
    loaded_at            timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, station_id)
);

-- Landed **wide** (one row per ts+region, one column per fuel type),
-- not the long/per-fuel-type-row shape the original schema assumed --
-- see this migration's own header note.
DROP TABLE IF EXISTS raw.openelectricity_mix;
CREATE TABLE raw.openelectricity_mix (
    ts                             timestamptz NOT NULL,
    region                         text        NOT NULL,
    network_code                   text,
    demand_mw                      numeric,
    price_mwh                      numeric,
    total_generation_mw            numeric,
    total_renewable_mw             numeric,
    intensity_kg_per_mwh           numeric,
    battery_discharge_mw           numeric,
    battery_charge_mw              numeric,
    biomass_mw                     numeric,
    coal_mw                        numeric,
    distillate_mw                  numeric,
    gas_mw                         numeric,
    hydro_mw                       numeric,
    pumped_hydro_mw                numeric,
    solar_rooftop_mw               numeric,
    solar_utility_mw               numeric,
    wind_mw                        numeric,
    source                         text,
    ingested_at                    timestamptz,
    ingest_run_id                  uuid,
    loaded_at                      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, region)
);

DROP TABLE IF EXISTS raw.aemo_holidays;
CREATE TABLE raw.aemo_holidays (
    date           date NOT NULL,
    region         text NOT NULL,
    holiday_name   text,
    is_workday     boolean,
    source         text,
    ingested_at    timestamptz,
    ingest_run_id  uuid,
    loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (region, date)
);
