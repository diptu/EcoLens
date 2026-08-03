-- 0014_data_sources.sql — persisted admin-editable config for
-- `GET/PATCH /v1/data-sources[/{id}]` (API_SPECEFICATIONS.md §1). Static
-- deployment config (name, category, default cron, URL, license, ...)
-- lives in `ecolens.datasources.catalog`; the columns here are the
-- overrides `PATCH /v1/data-sources/{id}` can actually write, plus the
-- `version`/`updated_at` optimistic-concurrency PATCH needs (`If-Match`).
--
-- `cron`/`timezone`/`description`/`auth_type` are nullable: NULL means
-- "no override, use the catalog default" (see `ecolens.datasources.
-- service._build_entry`). `metadata` merges on top of the catalog's
-- metadata dict rather than replacing it, so it defaults to `{}` (merging
-- an empty object is a no-op) rather than NULL.

CREATE TABLE IF NOT EXISTS meta.data_sources (
    id           text        PRIMARY KEY,
    enabled      boolean     NOT NULL DEFAULT true,
    cron         text,
    timezone     text,
    description  text,
    auth_type    text,
    metadata     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    version      integer     NOT NULL DEFAULT 1,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Seed one row per ecolens.datasources.catalog.CATALOG entry.
INSERT INTO meta.data_sources (id) VALUES
    ('ds-oe'),
    ('ds-aemo-nem'),
    ('ds-aemo-wem'),
    ('ds-bom'),
    ('ds-holidays')
ON CONFLICT (id) DO NOTHING;
