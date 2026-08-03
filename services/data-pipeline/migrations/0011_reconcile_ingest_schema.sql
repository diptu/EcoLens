-- 0011_reconcile_ingest_schema.sql — align the schema with what the
-- ingestion tasks (ecolens/pipeline/tasks/*.py, ecolens/pipeline/tasks/_common.py)
-- and the dbt staging models (models/staging/stg_*.sql) actually expect.
-- Migrations 0002-0007 predate those and defined narrower/differently
-- shaped tables.
--
-- Originally this just DROPped and recreated all 6 affected tables,
-- on the assumption that none of them could have real data yet. That
-- assumption doesn't hold in every environment — re-pointing this
-- service at a database an earlier/different ingestion run already
-- populated (richer columns: per-sub-fuel breakdowns, anomaly-detector
-- fields, `fetched_at` instead of `ingested_at`, etc.) hit exactly this
-- migration trying to drop ~68,000 real rows of AEMO/BoM history out
-- from under it. Fixed to check emptiness per table first:
--   * empty            → DROP + recreate with the plain target shape
--     (original behavior, unaffected)
--   * has existing rows → ADD the columns dbt/ingestion code expects
--     (backfilled from whatever richer columns are already there) and
--     leave every existing column and row alone — no data loss either
--     way.
--
-- Affected:
--   * meta._ingest_log        — richer run-audit columns (window,
--                                triggered_by, hostname, circuit state)
--   * raw.aemo_nem_dispatch   — per-fuel generation columns, not just demand/price
--   * raw.aemo_wem_dispatch   — same, plus WEM-specific fuels (diesel)
--   * raw.bom_observations    — full BoM observation fields
--   * raw.openelectricity_mix — wide form (one row per ts+region), not
--                                long form (one row per ts+region+fuel)
--   * raw.aemo_holidays       — `date` column (was `holiday_date`), plus
--                                `is_workday`/`ingest_run_id`
--
-- Idempotent: safe to re-run (DROP ... IF EXISTS, CREATE ... IF NOT EXISTS,
-- ADD COLUMN IF NOT EXISTS, UPDATE ... WHERE <col> IS NULL).

-- ── meta._ingest_log ────────────────────────────────────────────────────
DO $$
BEGIN
    IF (SELECT count(*) FROM meta._ingest_log) = 0 THEN
        EXECUTE 'DROP TABLE meta._ingest_log';
        EXECUTE $ddl$
            CREATE TABLE meta._ingest_log (
                id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                source                 text        NOT NULL,
                status                 text        NOT NULL,
                triggered_by           text        NOT NULL DEFAULT 'manual',
                window_start           text,
                window_end             text,
                hostname               text,
                started_at             timestamptz NOT NULL DEFAULT now(),
                finished_at            timestamptz,
                rows_landed            integer,
                rows_loaded            integer,
                error_message          text,
                circuit_breaker_state  text
            )
        $ddl$;
    END IF;
END $$;

-- ── raw.aemo_nem_dispatch ───────────────────────────────────────────────
DO $$
BEGIN
    IF (SELECT count(*) FROM raw.aemo_nem_dispatch) = 0 THEN
        EXECUTE 'DROP TABLE raw.aemo_nem_dispatch';
        EXECUTE $ddl$
            CREATE TABLE raw.aemo_nem_dispatch (
                ts                 timestamptz NOT NULL,
                region              text        NOT NULL,
                demand_mw           numeric,
                price_mwh           numeric,
                coal_mw              numeric,
                gas_mw               numeric,
                hydro_mw             numeric,
                wind_mw              numeric,
                solar_utility_mw     numeric,
                solar_rooftop_mw     numeric,
                battery_mw           numeric,
                net_import_mw        numeric,
                source               text,
                ingested_at          timestamptz NOT NULL DEFAULT now(),
                ingest_run_id        uuid,
                PRIMARY KEY (ts, region)
            )
        $ddl$;
    ELSE
        EXECUTE 'ALTER TABLE raw.aemo_nem_dispatch
            ADD COLUMN IF NOT EXISTS coal_mw numeric,
            ADD COLUMN IF NOT EXISTS gas_mw numeric,
            ADD COLUMN IF NOT EXISTS battery_mw numeric,
            ADD COLUMN IF NOT EXISTS ingested_at timestamptz';
        UPDATE raw.aemo_nem_dispatch SET
            coal_mw = COALESCE(coal_black_mw, 0) + COALESCE(coal_brown_mw, 0),
            gas_mw = COALESCE(gas_ccgt_mw, 0) + COALESCE(gas_ocgt_mw, 0) + COALESCE(gas_other_mw, 0),
            battery_mw = COALESCE(battery_discharge_mw, 0) - COALESCE(battery_charge_mw, 0),
            ingested_at = fetched_at
        WHERE coal_mw IS NULL;
    END IF;
END $$;

-- ── raw.aemo_wem_dispatch ───────────────────────────────────────────────
DO $$
BEGIN
    IF (SELECT count(*) FROM raw.aemo_wem_dispatch) = 0 THEN
        EXECUTE 'DROP TABLE raw.aemo_wem_dispatch';
        EXECUTE $ddl$
            CREATE TABLE raw.aemo_wem_dispatch (
                ts                  timestamptz NOT NULL,
                region               text        NOT NULL,
                demand_mw            numeric,
                price_mwh            numeric,
                coal_mw              numeric,
                gas_mw               numeric,
                diesel_mw            numeric,
                wind_mw              numeric,
                solar_utility_mw     numeric,
                solar_rooftop_mw     numeric,
                battery_mw           numeric,
                biomass_mw           numeric,
                total_generation_mw  numeric,
                source               text,
                ingested_at          timestamptz NOT NULL DEFAULT now(),
                ingest_run_id        uuid,
                PRIMARY KEY (ts, region)
            )
        $ddl$;
    ELSE
        EXECUTE 'ALTER TABLE raw.aemo_wem_dispatch
            ADD COLUMN IF NOT EXISTS coal_mw numeric,
            ADD COLUMN IF NOT EXISTS gas_mw numeric,
            ADD COLUMN IF NOT EXISTS diesel_mw numeric,
            ADD COLUMN IF NOT EXISTS battery_mw numeric,
            ADD COLUMN IF NOT EXISTS ingested_at timestamptz';
        -- WEM's existing data has `distillate_mw`, not `diesel_mw` — same
        -- fuel, different name (AEMO's own WEM terminology); mapped
        -- straight across, not summed with anything else.
        UPDATE raw.aemo_wem_dispatch SET
            coal_mw = COALESCE(coal_black_mw, 0) + COALESCE(coal_brown_mw, 0),
            gas_mw = COALESCE(gas_ccgt_mw, 0) + COALESCE(gas_ocgt_mw, 0) + COALESCE(gas_other_mw, 0),
            diesel_mw = distillate_mw,
            battery_mw = COALESCE(battery_discharge_mw, 0) - COALESCE(battery_charge_mw, 0),
            ingested_at = fetched_at
        WHERE coal_mw IS NULL;
    END IF;
END $$;

-- ── raw.bom_observations ────────────────────────────────────────────────
DO $$
BEGIN
    IF (SELECT count(*) FROM raw.bom_observations) = 0 THEN
        EXECUTE 'DROP TABLE raw.bom_observations';
        EXECUTE $ddl$
            CREATE TABLE raw.bom_observations (
                ts                   timestamptz NOT NULL,
                station_id            text        NOT NULL,
                region                text        NOT NULL,
                temp_c                numeric,
                apparent_temp_c       numeric,
                dew_point_c           numeric,
                humidity_pct          numeric,
                wind_speed_kmh        numeric,
                wind_direction_deg    numeric,
                wind_gust_kmh         numeric,
                pressure_hpa          numeric,
                rain_since_9am_mm     numeric,
                cloud_oktas           numeric,
                source                text,
                ingested_at           timestamptz NOT NULL DEFAULT now(),
                ingest_run_id         uuid,
                PRIMARY KEY (ts, station_id)
            )
        $ddl$;
    ELSE
        EXECUTE 'ALTER TABLE raw.bom_observations
            ADD COLUMN IF NOT EXISTS ingested_at timestamptz';
        UPDATE raw.bom_observations SET ingested_at = fetched_at
        WHERE ingested_at IS NULL;
    END IF;
END $$;

-- ── raw.openelectricity_mix ─────────────────────────────────────────────
-- Wide form now (one row per ts+network+region), replacing the original
-- long-form design (one row per ts+region+fuel_type) from migration 0002.
DO $$
BEGIN
    IF (SELECT count(*) FROM raw.openelectricity_mix) = 0 THEN
        EXECUTE 'DROP TABLE raw.openelectricity_mix';
        EXECUTE $ddl$
            CREATE TABLE raw.openelectricity_mix (
                ts                       timestamptz NOT NULL,
                network_code              text        NOT NULL,
                region                    text        NOT NULL,
                coal_mw                   numeric,
                gas_mw                    numeric,
                hydro_mw                  numeric,
                wind_mw                   numeric,
                solar_utility_mw          numeric,
                solar_rooftop_mw          numeric,
                battery_discharge_mw      numeric,
                battery_charge_mw         numeric,
                pumped_hydro_mw           numeric,
                biomass_mw                numeric,
                distillate_mw             numeric,
                total_generation_mw       numeric,
                total_renewable_mw        numeric,
                demand_mw                 numeric,
                price_mwh                 numeric,
                intensity_kg_per_mwh      numeric,
                source                    text,
                ingested_at               timestamptz NOT NULL DEFAULT now(),
                ingest_run_id             uuid,
                PRIMARY KEY (ts, network_code, region)
            )
        $ddl$;
    END IF;
    -- No ELSE: if this table ever has real rows in some other
    -- environment, leave it alone rather than guess at a reconciliation
    -- no version of this codebase has actually needed yet.
END $$;

-- ── raw.aemo_holidays ───────────────────────────────────────────────────
DO $$
BEGIN
    IF (SELECT count(*) FROM raw.aemo_holidays) = 0 THEN
        EXECUTE 'DROP TABLE raw.aemo_holidays';
        EXECUTE $ddl$
            CREATE TABLE raw.aemo_holidays (
                date            date NOT NULL,
                region          text NOT NULL,
                holiday_name    text NOT NULL,
                is_workday      boolean     NOT NULL DEFAULT false,
                source          text,
                ingested_at     timestamptz NOT NULL DEFAULT now(),
                ingest_run_id   uuid,
                PRIMARY KEY (region, date)
            )
        $ddl$;
    ELSE
        EXECUTE 'ALTER TABLE raw.aemo_holidays
            ADD COLUMN IF NOT EXISTS is_workday boolean,
            ADD COLUMN IF NOT EXISTS ingested_at timestamptz';
        -- Existing data calls this `is_business_day`, same meaning.
        UPDATE raw.aemo_holidays SET
            is_workday = is_business_day,
            ingested_at = fetched_at
        WHERE is_workday IS NULL;
    END IF;
END $$;
