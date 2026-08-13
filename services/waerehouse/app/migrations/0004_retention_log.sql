-- 0004_retention_log.sql — one row per `export_and_prune_and_vacuum_task`
-- run (`app/tasks/retention_tasks.py`, root TODO.md's "Vacuum Database"
-- item, "Scheduled Operations" item's retention-visibility follow-up).
--
-- Same shape/reasoning as `meta._dbt_build_log` (`0001_raw_schema.sql`'s
-- neighbor, created directly against the real NeonDB, not tracked in a
-- migration file here either — this table follows that same real,
-- already-established `meta.*` audit-log pattern, just newly formalized
-- as a tracked migration since it didn't exist before this one).
-- `pruned`/`vacuumed` are jsonb, not separate per-table columns — the
-- table set this task touches (`raw.*`'s prunable tables) can grow
-- without a schema migration every time one does.

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta._retention_log (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger      text        NOT NULL,
    triggered_by text        NOT NULL,
    status       text        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    pruned       jsonb,
    vacuumed     jsonb,
    error        text
);
