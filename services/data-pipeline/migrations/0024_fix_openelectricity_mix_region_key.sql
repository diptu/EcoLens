-- 0024_fix_openelectricity_mix_region_key.sql — fixes a real uniqueness
-- bug found 2026-08-05 while landing genuinely region-scoped OE data for
-- the first time (`todo-model-training.md`'s OE region-join blocker).
--
-- Migration 0011 defines `raw.openelectricity_mix` with
-- `PRIMARY KEY (ts, network_code, region)` -- but that CREATE TABLE only
-- runs when the table is empty. On any environment that instead went
-- through 0020's legacy-adoption path (renaming an old
-- `raw.openelectricity_responses` table onto `openelectricity_mix`),
-- 0020 just renamed whatever constraint the legacy table already had
-- (`openelectricity_responses_network_code_ts_key`) rather than
-- reconciling it against 0011's intended shape -- and that legacy
-- constraint was `UNIQUE (network_code, ts)`, missing `region` entirely.
--
-- Confirmed live: with genuinely per-region data (multiple NEM regions
-- sharing the same `ts`, now that `ingest_openelectricity.py` queries
-- each region separately instead of relabeling one network-wide
-- fetch), `load_to_postgres`'s `ON CONFLICT DO NOTHING` used this
-- constraint and silently dropped every region after the first one to
-- land for a given `(network_code, ts)` -- 6 regions' worth of real
-- data staged, only 2 actually reached the table.
--
-- Idempotent: only touches the constraint if it's still the old,
-- region-missing shape.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'raw.openelectricity_mix'::regclass
          AND conname = 'openelectricity_mix_network_code_ts_key'
    ) THEN
        ALTER TABLE raw.openelectricity_mix
            DROP CONSTRAINT openelectricity_mix_network_code_ts_key;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conrelid = 'raw.openelectricity_mix'::regclass
          AND contype = 'p'
    ) THEN
        ALTER TABLE raw.openelectricity_mix
            ADD PRIMARY KEY (ts, network_code, region);
    END IF;
END $$;
