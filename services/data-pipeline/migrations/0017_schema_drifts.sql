-- 0017_schema_drifts.sql — tracks schema drift on the 5 raw.* tables
-- (`ecolens.pipeline.schema_drift`), backing `GET /v1/data-quality/schema`
-- (API_SPECEFICATIONS.md §3.4). One row per (table, column, kind) that's
-- currently drifted from the expected schema
-- (`pipeline.schema_drift._EXPECTED_COLUMNS`, sourced from
-- docs/data/ingestion-schema.md) — `first_seen_at` is fixed on first
-- detection, `last_checked_at` bumps on every subsequent detection run
-- that still finds the same drift; a row is deleted once a detection run
-- no longer finds that drift (schema reverted, or the gap was closed).

CREATE TABLE IF NOT EXISTS meta.schema_drifts (
    id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source           text        NOT NULL,
    table_name       text        NOT NULL,
    severity         text        NOT NULL,
    kind             text        NOT NULL,
    column_name      text        NOT NULL,
    old_type         text,
    new_type         text,
    auto_adapted     boolean     NOT NULL DEFAULT false,
    action_required  boolean     NOT NULL DEFAULT true,
    downstream_impact text,
    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    last_checked_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (table_name, column_name, kind)
);

CREATE INDEX IF NOT EXISTS idx_schema_drifts_source ON meta.schema_drifts (source);
