-- 0006_anomaly_status.sql — adds a real acknowledge/resolve/false-
-- positive workflow to `meta.anomalies` (root TODO.md's "make every
-- page fully functional with real data" -- the dashboard's anomaly-
-- detection page previously had these 3 actions as local-state-only
-- mock mutations with no real backend at all).
--
-- `meta.anomalies` itself already exists (created by services/
-- ingestion's own `pipeline.anomaly.record_anomalies`, real, 142K+
-- real rows confirmed live 2026-08-08) -- this migration only adds the
-- 2 new columns a real status workflow needs. Additive, non-destructive
-- (`ADD COLUMN ... DEFAULT` is a metadata-only change in Postgres 11+,
-- no table rewrite/lock cost even at this row count).

ALTER TABLE meta.anomalies ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'new';
ALTER TABLE meta.anomalies ADD COLUMN IF NOT EXISTS status_updated_at timestamptz;
