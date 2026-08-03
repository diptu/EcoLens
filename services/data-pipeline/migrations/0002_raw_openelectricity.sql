-- 0002_raw_openelectricity.sql — OpenElectricity generation mix + emissions
-- intensity, landed long-form (see docs/data/ingestion-schema.md).

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
