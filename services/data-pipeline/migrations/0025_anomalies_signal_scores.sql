-- 0025_anomalies_signal_scores.sql — per-signal breakdown for the hybrid
-- detector's three signals (rule-based, statistical, ML), so which
-- signal(s) actually triggered on a flagged row is a queryable structured
-- field instead of only present in `anomaly_reason`'s free-text string.
-- `services/ingestion/TODO.md`'s "Remaining Work" §2, deliberately deferred
-- from the original hybrid-detector pass.
--
-- `metric`/`value`/`z_score`/`expected_low`/`expected_high` (0016) already
-- capture the single worst-offending (metric, value) pair used to drive
-- `anomaly_score` and `GET /v1/data-quality/outliers` — unchanged here.
-- These three columns are additive: one nullable numeric per signal
-- category, NULL meaning that signal did not fire for this row, non-NULL
-- being that signal's own score (independent of which signal ended up
-- "winning" `anomaly_score`). A row flagged by both rule-based and ML
-- checks now has both `rule_based_score` and `ml_score` populated, even
-- though only one of them drove the overall `anomaly_score`/`metric`.
--
-- `services/ingestion` only (`services/data-pipeline`'s own copy of the
-- detector is the frozen legacy 2-signal version, predating the ML
-- signal entirely — it never populates these, and that's fine, they're
-- nullable).

ALTER TABLE meta.anomalies
    ADD COLUMN IF NOT EXISTS rule_based_score  numeric,
    ADD COLUMN IF NOT EXISTS statistical_score numeric,
    ADD COLUMN IF NOT EXISTS ml_score          numeric;

CREATE INDEX IF NOT EXISTS idx_anomalies_ml_score
    ON meta.anomalies (ml_score) WHERE ml_score IS NOT NULL;
