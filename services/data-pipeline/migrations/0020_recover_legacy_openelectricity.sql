-- 0020_recover_legacy_openelectricity.sql — some environments have a
-- `raw.openelectricity_responses` table (17k+ real rows spanning a
-- month) from an ingestion run that predates this table's rename to
-- `raw.openelectricity_mix` (0002/0011). Migration 0011 only reconciles
-- `openelectricity_mix` when IT already has rows — it doesn't know to
-- look at the old, differently-named table at all, so on a database
-- like this one it just left a real, valuable, correctly-shaped
-- (same enriched schema as the other 4 raw tables) dataset sitting
-- under a name nothing in the current codebase reads from.
--
-- Recovers it: if `openelectricity_responses` exists and has rows, and
-- `openelectricity_mix` is still empty, adopt the legacy table (rename)
-- rather than leaving it orphaned, then add the handful of columns the
-- current schema wants that the legacy one didn't have — backfilled
-- from real data (computed aggregates / same-value renames), not left
-- NULL.
--
-- Idempotent: no-ops if `openelectricity_responses` doesn't exist, or
-- if `openelectricity_mix` already has rows (nothing to adopt into).

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'raw' AND table_name = 'openelectricity_responses'
    )
    AND (SELECT count(*) FROM raw.openelectricity_responses) > 0
    AND (SELECT count(*) FROM raw.openelectricity_mix) = 0
    THEN
        -- CASCADE: only ever drops dbt-built staging/mart views downstream
        -- (derived, rebuilt by the next `dbt run`), never raw data.
        EXECUTE 'DROP TABLE raw.openelectricity_mix CASCADE';
        EXECUTE 'ALTER TABLE raw.openelectricity_responses RENAME TO openelectricity_mix';
        EXECUTE 'ALTER TABLE raw.openelectricity_mix RENAME CONSTRAINT
            openelectricity_responses_network_code_ts_key TO openelectricity_mix_network_code_ts_key';

        EXECUTE 'ALTER TABLE raw.openelectricity_mix
            ADD COLUMN IF NOT EXISTS coal_mw numeric,
            ADD COLUMN IF NOT EXISTS gas_mw numeric,
            ADD COLUMN IF NOT EXISTS total_renewable_mw numeric,
            ADD COLUMN IF NOT EXISTS intensity_kg_per_mwh numeric,
            ADD COLUMN IF NOT EXISTS ingested_at timestamptz';

        UPDATE raw.openelectricity_mix SET
            coal_mw = COALESCE(coal_black_mw, 0) + COALESCE(coal_brown_mw, 0),
            gas_mw = COALESCE(gas_ccgt_mw, 0) + COALESCE(gas_ocgt_mw, 0) + COALESCE(gas_other_mw, 0),
            total_renewable_mw = COALESCE(wind_mw, 0) + COALESCE(solar_utility_mw, 0)
                + COALESCE(solar_rooftop_mw, 0) + COALESCE(hydro_mw, 0)
                + COALESCE(pumped_hydro_mw, 0) + COALESCE(biomass_mw, 0),
            intensity_kg_per_mwh = emissions_intensity_kgco2e_per_mwh,
            ingested_at = fetched_at
        WHERE coal_mw IS NULL;
    END IF;
END $$;
