-- 0006_raw_aemo_holidays.sql — annual public-holiday calendar snapshot,
-- per region. See docs/data/ingestion-schema.md.

CREATE TABLE IF NOT EXISTS raw.aemo_holidays (
    region        text        NOT NULL,
    holiday_date  date        NOT NULL,
    holiday_name  text        NOT NULL,
    ingested_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (region, holiday_date)
);
