-- 0001_init.sql — base schemas, pgcrypto, and the migration-tracking table.
-- Idempotent: safe to re-run (see scripts/apply-migrations.sh).

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS intermediate;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS ml;
CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.schema_migrations (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    filename    text NOT NULL UNIQUE,
    applied_at  timestamptz NOT NULL DEFAULT now()
);

INSERT INTO meta.schema_migrations (filename)
VALUES ('0001_init.sql')
ON CONFLICT (filename) DO NOTHING;
