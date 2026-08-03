-- 0004_raw_aemo_wem.sql — AEMO WEM (SWIS) 30-min dispatch, single region.
-- See docs/data/ingestion-schema.md.

CREATE TABLE IF NOT EXISTS raw.aemo_wem_dispatch (
    ts             timestamptz NOT NULL,
    region         text        NOT NULL,
    demand_mw      numeric,
    price          numeric,
    source_run_id  uuid,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (ts, region)
);
