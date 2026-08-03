-- 0003_raw_aemo_nem.sql — AEMO NEM 5-min dispatch, per region
-- (NSW1/QLD1/VIC1/SA1/TAS1). See docs/data/ingestion-schema.md.

CREATE TABLE IF NOT EXISTS raw.aemo_nem_dispatch (
    ts             timestamptz NOT NULL,
    region         text        NOT NULL,
    demand_mw      numeric,
    price          numeric,
    source_run_id  uuid,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, region)
);
