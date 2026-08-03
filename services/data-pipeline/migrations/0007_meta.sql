-- 0007_meta.sql — operational bookkeeping tables. See
-- docs/data/ingestion-schema.md for what each one is for.

CREATE TABLE IF NOT EXISTS meta._ingest_log (
    run_id       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source       text        NOT NULL,
    status       text        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    rows_loaded  integer,
    error        text
);

-- Postgres mirror of the Redis-backed CircuitBreaker (ECO-D07). Redis
-- stays the source of truth the breaker actually reads from; this is for
-- durability/auditing across Redis restarts.
CREATE TABLE IF NOT EXISTS meta.circuit_breaker_state (
    name        text PRIMARY KEY,
    state       text        NOT NULL,
    failures    integer     NOT NULL DEFAULT 0,
    opened_at   timestamptz,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS meta.cron_run_log (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name     text        NOT NULL,
    started_at   timestamptz NOT NULL DEFAULT now(),
    finished_at  timestamptz,
    exit_code    integer,
    output       text
);

CREATE TABLE IF NOT EXISTS meta._promotion_log (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name         text        NOT NULL,
    promoted           boolean     NOT NULL,
    candidate_version  text        NOT NULL,
    candidate_mape     numeric,
    production_mape    numeric,
    reason             text,
    created_at         timestamptz NOT NULL DEFAULT now()
);
