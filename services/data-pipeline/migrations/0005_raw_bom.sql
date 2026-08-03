-- 0005_raw_bom.sql — BoM weather observations, 6 stations (one per NEM
-- region + WEM). See docs/data/ingestion-schema.md.

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
