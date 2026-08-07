-- 0003_mart_floor_checks.sql — one row per time-series mart, the
-- earliest `ts`/`hour` this service last observed in it
-- (`app/retention/mart_floor_monitor.py`, `TODO.md` Phase 1's deferred
-- "assert min(ts) never moves forward" follow-up).
--
-- Lives in `meta` (created defensively here, `IF NOT EXISTS` — the
-- schema itself already exists in the real NeonDB, created by
-- data-pipeline's own migrations, same "this service's own copy of the
-- same DDL" reasoning `0001_raw_schema.sql`'s header already explains
-- for `raw`) rather than `raw_marts` — this is this service's own
-- operational bookkeeping about the marts, not mart data itself.
--
-- Why Postgres, not Prometheus, for the "previous value" comparison:
-- the comparison needs to survive between separate, short-lived
-- `ecolens-warehouse check-mart-history` invocations (the scheduled
-- GitHub Actions job — `.github/workflows/warehouse-monitor.yml` —
-- each run is a fresh process with no memory of the last one).
-- Prometheus's own scrape history would work too, but only for
-- whichever process is actually being scraped — a CI job isn't, and
-- there's no production deploy URL yet for it to instead scrape-then-
-- compare against. This table is the one thing both a CLI invocation
-- and the real deployed service always share: the same production
-- database.

CREATE SCHEMA IF NOT EXISTS meta;

CREATE TABLE IF NOT EXISTS meta.mart_floor_checks (
    mart         text        PRIMARY KEY,
    min_ts       timestamptz NOT NULL,
    checked_at   timestamptz NOT NULL DEFAULT now()
);
