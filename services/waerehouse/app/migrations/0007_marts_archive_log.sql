-- 0007_marts_archive_log.sql — targets the PRIMARY database
-- (Settings.database_url / DATABASE_URL), NOT RAW_MARTS_DATABASE_URL.
--
-- One row per `archive_and_prune_marts_task` run (`app/tasks/
-- marts_archive_tasks.py`) — same start/finish audit-trail shape as
-- `meta._retention_log` (0004) and `meta._dbt_build_log`. Closes the gap
-- `app/retention/pruning.py`'s own module docstring names explicitly:
-- "Curated (dbt marts) retention is a documented follow-up, not
-- implemented here... deserve their own pass rather than a rushed
-- guess" — root TODO.md's "save raw and raw.marts in seperate database"
-- item.
--
-- `archived`/`pruned` are jsonb (per-table row counts), not separate
-- columns, same reasoning `meta._retention_log.pruned` already uses —
-- the table set this task touches can grow without a migration every
-- time dbt adds a new mart.

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta._marts_archive_log (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger      text        NOT NULL,
    triggered_by text        NOT NULL,
    status       text        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    cutoff       timestamptz,
    archived     jsonb,
    pruned       jsonb,
    error        text
);
