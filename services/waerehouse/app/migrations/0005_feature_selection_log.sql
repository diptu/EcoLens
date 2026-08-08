-- 0005_feature_selection_log.sql — one row per real automated
-- feature-selection run (`services/ingestion/scripts/select_features.py`'s
-- `run_selection()`, root TODO.md's "System Commands" Rebuild Features
-- item). Lives in `meta` alongside `_dbt_build_log`/`_retention_log`
-- (this repo's convention: cross-service `meta.*` migrations tracked
-- here even when the writing code lives in a different service --
-- `services/ingestion` has no migrations directory of its own).
--
-- `result` is the full real `run_selection()` return value (selected
-- features + per-feature scores + per-region row/candidate counts) as
-- jsonb, not split into columns -- same reasoning `_retention_log`'s
-- `pruned`/`vacuumed` jsonb columns already use (the shape can grow
-- without a schema migration every time).

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta._feature_selection_log (
    id           uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    triggered_by text        NOT NULL,
    status       text        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    n_selected   integer,
    result       jsonb,
    error        text
);
