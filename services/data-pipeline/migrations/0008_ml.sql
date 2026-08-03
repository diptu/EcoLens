-- 0008_ml.sql — training/evaluation bookkeeping tables. See
-- docs/data/ingestion-schema.md.

CREATE TABLE IF NOT EXISTS ml.forecast_runs (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name     text        NOT NULL,
    model_version  text,
    region         text        NOT NULL,
    generated_at   timestamptz NOT NULL DEFAULT now(),
    horizon        text        NOT NULL,
    interval       text        NOT NULL
);

CREATE TABLE IF NOT EXISTS ml.eval_reports (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name     text        NOT NULL,
    model_version  text,
    evaluated_at   timestamptz NOT NULL DEFAULT now(),
    window_days    integer     NOT NULL,
    mape           numeric,
    rmse           numeric,
    mae            numeric,
    p90_coverage   numeric
);

CREATE TABLE IF NOT EXISTS ml.drift_reports (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    model_name    text        NOT NULL,
    checked_at    timestamptz NOT NULL DEFAULT now(),
    psi           numeric,
    ks_statistic  numeric,
    drifted       boolean     NOT NULL DEFAULT false,
    report_url    text
);
