-- 0018_pipelines.sql — pause/resume bookkeeping for
-- `API_SPECEFICATIONS.md` §2 (`GET /v1/ingestion/pipelines`,
-- `POST /v1/ingestion/{id}/{pause,resume}`). Static pipeline definitions
-- (name, stage, cron, depends_on) live in `ecolens.pipelines.catalog`,
-- same split `0014_data_sources.sql`/`ecolens.datasources.catalog` already
-- use; this table only holds the one thing that's actually mutable at
-- runtime — whether a pipeline is paused, and the audit trail for that.
--
-- A pipeline's `id` is either 1:1 with a `meta.data_sources.id` (the 5
-- extract pipelines — `pipe-oe` <-> `ds-oe`, etc.) or has no data-source
-- counterpart at all (`pipe-dbt-warehouse`, the one transform pipeline).
-- Pausing a pipeline here is a *separate* switch from a data source's own
-- `enabled` flag (`meta.data_sources.enabled`, `PATCH /v1/data-sources/{id}`)
-- — the two admin surfaces are kept independent on purpose, matching how
-- `API_SPECEFICATIONS.md` documents them as separate concepts (source
-- config vs. pipeline/orchestration pause) even though today they mostly
-- overlap in what they gate.

CREATE TABLE IF NOT EXISTS meta.pipelines (
    id         text        PRIMARY KEY,
    status     text        NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    paused_at  timestamptz,
    paused_by  text,
    reason     text,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- Seed one row per ecolens.pipelines.catalog.PIPELINES entry.
INSERT INTO meta.pipelines (id) VALUES
    ('pipe-oe'),
    ('pipe-aemo-nem'),
    ('pipe-aemo-wem'),
    ('pipe-bom'),
    ('pipe-holidays'),
    ('pipe-dbt-warehouse')
ON CONFLICT (id) DO NOTHING;
