-- 0010_indexes.sql — composite (region, ts) indexes on the raw tables,
-- plus "latest N per model" indexes on the ML eval/drift report tables.
--
-- `raw.aemo_holidays`'s own index is intentionally NOT here: at this
-- point in the sequence its date column is still whatever 0006 named it
-- (`holiday_date`) on a database that has never had 0011 run against it
-- yet — but on a database an earlier/different ingestion run already
-- populated (already using 0011's `date` column, no `holiday_date` at
-- all), this would fail outright with "column does not exist". 0012
-- ("reapply ... after 0011 reconciles the schema") already (re)creates
-- this exact index against the reconciled `date` column in every case,
-- so it's not silently dropped — just correctly deferred until after
-- reconciliation instead of racing it.

CREATE INDEX IF NOT EXISTS idx_openelectricity_mix_region_ts
    ON raw.openelectricity_mix (region, ts DESC);

CREATE INDEX IF NOT EXISTS idx_aemo_nem_dispatch_region_ts
    ON raw.aemo_nem_dispatch (region, ts DESC);

CREATE INDEX IF NOT EXISTS idx_aemo_wem_dispatch_region_ts
    ON raw.aemo_wem_dispatch (region, ts DESC);

CREATE INDEX IF NOT EXISTS idx_bom_observations_region_ts
    ON raw.bom_observations (region, ts DESC);

CREATE INDEX IF NOT EXISTS idx_eval_reports_model_evaluated_at
    ON ml.eval_reports (model_name, evaluated_at DESC);

CREATE INDEX IF NOT EXISTS idx_drift_reports_model_checked_at
    ON ml.drift_reports (model_name, checked_at DESC);
