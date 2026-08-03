-- 0016_anomalies_outlier_fields.sql — structured fields for the single
-- worst-offending (metric, value) pair per flagged row, needed for
-- `GET /v1/data-quality/outliers` (API_SPECEFICATIONS.md §3.3) to be
-- real rather than trying to parse `anomaly_reason`'s free-text string
-- back apart. All nullable: a rule-based `missing_value` flag has a
-- `metric` but no `value`/bounds; only `statistical_outlier` flags get a
-- `z_score`.

ALTER TABLE meta.anomalies
    ADD COLUMN IF NOT EXISTS metric        text,
    ADD COLUMN IF NOT EXISTS value         numeric,
    ADD COLUMN IF NOT EXISTS z_score       numeric,
    ADD COLUMN IF NOT EXISTS expected_low  numeric,
    ADD COLUMN IF NOT EXISTS expected_high numeric;

CREATE INDEX IF NOT EXISTS idx_anomalies_z_score
    ON meta.anomalies (z_score) WHERE z_score IS NOT NULL;
