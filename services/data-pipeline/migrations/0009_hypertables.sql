-- 0009_hypertables.sql — convert the 5 raw time-series tables to
-- TimescaleDB hypertables (7-day chunks).
--
-- Idempotent via create_hypertable's own if_not_exists flag, and a no-op
-- (with a NOTICE) on Postgres instances that don't offer the timescaledb
-- extension at all — several managed/serverless providers (e.g. Neon)
-- don't allow it, and this migration must not fail the whole run just
-- because of that.
--
-- `migrate_data => true` on every call: `create_hypertable` refuses a
-- non-empty table by default. This is only ever hit when re-running
-- migrations against a database some previous ingestion run already
-- populated (e.g. re-pointing this service at an existing warehouse) —
-- a fresh database has nothing to migrate, so the flag is a no-op there.
--
-- `raw.aemo_holidays` is intentionally NOT converted here, unlike the
-- other 4 — at this point in the sequence its date column is still
-- whatever 0006 named it (`holiday_date`) on a database that's never
-- had 0011 run yet, but a database an earlier/different ingestion run
-- already populated has always used 0011's `date` column, no
-- `holiday_date` at all. 0012 ("reapply ... after 0011 reconciles the
-- schema") already converts it correctly against `date` in every case.
--
-- `CREATE EXTENSION IF NOT EXISTS` (not just checking
-- `pg_available_extensions`) still runs even when the extension is
-- already installed — on Neon's pooled connections that's occasionally
-- hit a "already loaded with another version" error against a backend
-- that served a previous `CREATE EXTENSION` call in this same
-- migration run, so skip straight past it when it's already installed.

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'
    ) THEN
        RAISE NOTICE 'timescaledb extension not available on this instance — skipping hypertable conversion.';
        RETURN;
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        CREATE EXTENSION timescaledb;
    END IF;

    PERFORM create_hypertable(
        'raw.openelectricity_mix', 'ts',
        chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE,
        migrate_data => TRUE
    );
    PERFORM create_hypertable(
        'raw.aemo_nem_dispatch', 'ts',
        chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE,
        migrate_data => TRUE
    );
    PERFORM create_hypertable(
        'raw.aemo_wem_dispatch', 'ts',
        chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE,
        migrate_data => TRUE
    );
    PERFORM create_hypertable(
        'raw.bom_observations', 'ts',
        chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE,
        migrate_data => TRUE
    );
END $$;
