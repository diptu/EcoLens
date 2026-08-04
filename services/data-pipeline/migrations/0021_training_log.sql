-- 0021_training_log.sql — real, queryable training-run history (Model
-- Operations TODO.md Phase 4). Nothing before this logged "a training
-- trigger fired/finished" anywhere outside MLflow itself, so there was
-- no way to answer "is a training run in flight right now" without
-- guessing from MLflow's own run list. Mirrors meta._ingest_log's
-- running -> success/failed state machine (see 0011_reconcile_ingest_
-- schema.sql), one row per `training_worker.handle_training_trigger`
-- invocation.

CREATE TABLE IF NOT EXISTS meta._training_log (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name    text        NOT NULL,
    status        text        NOT NULL,
    triggered_by  text        NOT NULL,
    regions       jsonb       NOT NULL,
    window_start  timestamptz NOT NULL,
    window_end    timestamptz NOT NULL,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    run_id        text,
    model_version text,
    error_message text,
    hostname      text
);

CREATE INDEX IF NOT EXISTS ix_training_log_started_at ON meta._training_log (started_at DESC);
