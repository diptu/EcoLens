-- 0015_anomalies.sql — flagged (not dropped) records from the hybrid
-- rule-based + statistical anomaly detector (`ecolens.pipeline.anomaly`,
-- `overview.md` §1 Anomaly Detection Layer). One row per flagged record,
-- not per run — a single run can flag zero or many rows.

CREATE TABLE IF NOT EXISTS meta.anomalies (
    id             uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id         uuid        NOT NULL REFERENCES meta._ingest_log(id),
    source         text        NOT NULL,
    table_name     text        NOT NULL,
    anomaly_score  numeric     NOT NULL,
    anomaly_reason text        NOT NULL,
    row_snapshot   jsonb       NOT NULL,
    detected_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_anomalies_run_id ON meta.anomalies (run_id);
CREATE INDEX IF NOT EXISTS idx_anomalies_source_detected
    ON meta.anomalies (source, detected_at DESC);
