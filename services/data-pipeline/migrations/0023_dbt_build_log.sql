-- 0023_dbt_build_log.sql — real, queryable dbt-build history (TODO.md's
-- backfill section, "Follow-up" item). Mirrors meta._training_log's
-- running -> success/failed state machine (0021_training_log.sql), one
-- row per logged `run_dbt` invocation.
--
-- `trigger` vs `triggered_by`: `trigger` is the coarse call-site category
-- ("backfill_auto" | "dashboard_manual" | "admin_api" — see
-- `app.service.pipeline.dbt_build_log`'s module docstring for the exact
-- set), `triggered_by` is the free-form identifier already threaded
-- through each call site (a backfill's source id, "dashboard", or the
-- authenticated admin principal's `sub`).
--
-- Not every `run_dbt` caller in this codebase writes here yet (the
-- Prefect `dbt-build` task in `pipeline.flows` and the `ecolens-pipeline
-- dbt *` CLI commands still don't) — see `dbt_build_log.py`'s docstring
-- for the honest current coverage, same "don't claim more than what's
-- real" convention as this file's `meta._training_log` counterpart.

CREATE TABLE IF NOT EXISTS meta._dbt_build_log (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    subcommand    text        NOT NULL,
    target        text        NOT NULL,
    trigger       text        NOT NULL,
    triggered_by  text        NOT NULL,
    status        text        NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    exit_code     integer,
    error         text
);

CREATE INDEX IF NOT EXISTS ix_dbt_build_log_started_at ON meta._dbt_build_log (started_at DESC);
