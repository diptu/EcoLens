-- 0012_reapply_hypertables_and_indexes.sql — 0011 DROPped and recreated
-- the 5 raw.* tables, which also drops their hypertable status (0009)
-- and indexes (0010). Re-apply both here, against the reconciled schema
-- (`raw.aemo_holidays` now keys on `date`, not `holiday_date`).
--
-- Idempotent, same as 0009: no-ops with a NOTICE if timescaledb isn't
-- available on this instance.

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
    PERFORM create_hypertable(
        'raw.aemo_holidays', 'date',
        chunk_time_interval => INTERVAL '7 days', if_not_exists => TRUE,
        migrate_data => TRUE
    );
END $$;

CREATE INDEX IF NOT EXISTS idx_openelectricity_mix_region_ts
    ON raw.openelectricity_mix (region, ts DESC);

CREATE INDEX IF NOT EXISTS idx_aemo_nem_dispatch_region_ts
    ON raw.aemo_nem_dispatch (region, ts DESC);

CREATE INDEX IF NOT EXISTS idx_aemo_wem_dispatch_region_ts
    ON raw.aemo_wem_dispatch (region, ts DESC);

CREATE INDEX IF NOT EXISTS idx_bom_observations_region_ts
    ON raw.bom_observations (region, ts DESC);

CREATE INDEX IF NOT EXISTS idx_aemo_holidays_region_date
    ON raw.aemo_holidays (region, date DESC);
