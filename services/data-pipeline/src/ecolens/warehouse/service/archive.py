"""Stage 6: trim raw.* + VACUUM the warehouse.

Historically this stage deleted raw Mongo docs older than
`archive_after_days` -- the idea being that DuckDB held a durable
"cold storage" backup, so the live Mongo cluster didn't need to keep
years of raw history forever. Now that DuckDB is the sole *permanent*
raw store (see TODO.md's ECO-150..158 for that migration), that
original concern -- deleting rows with no backup -- no longer applies
to DuckDB, which `archive()` still never touches.

It does apply to Postgres `raw.*` though, and in the other direction:
`raw.*` is just a synced *working copy* of DuckDB for dbt to build
from (`ecolens.ingestion.repository.raw_sync`), safely rebuildable any
time via `--full`. Left untrimmed it regrows without bound and repeatedly
blew through NeonDB's 512MB free-tier project cap this project has hit
(see TODO.md) -- `archive()` now trims each raw.* time-series table to
`settings.raw_retention_days` (default 30d) every run, mirroring the
manual `DELETE ... WHERE ts < now() - interval '30 days'` + `VACUUM
FULL` that had to be run by hand each time the cap was hit.

Vacuum uses a plain synchronous psycopg2 connection rather than
asyncpg: `VACUUM` cannot run through asyncpg's extended query
protocol (Postgres rejects it — the same restriction that blocks
VACUUM inside a transaction block also blocks it from a prepared
statement), so a simple, un-pooled sync connection is the standard
workaround. The same connection is reused for the trim DELETEs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg2

from ecolens.shared.observability.logging import get_logger

from ecolens.warehouse.model.run_result import StageResult
from ecolens.warehouse.core.runner_settings import WarehouseRunnerSettings

log = get_logger(__name__)

VACUUM_TABLES: list[str] = [
    "fact_demand_30min",
    "ml_features_demand_v1",
    # Trimmed by archive() every run -- VACUUM (not FULL: this repo's
    # earlier storage-cap incidents were resolved with a one-off manual
    # VACUUM FULL for the multi-month deleted backlog; ordinary VACUUM
    # is enough to keep steady-state dead-tuple growth in check once
    # each cycle's trim is roughly offsetting new inserts) reclaims the
    # dead tuples the DELETEs above leave behind.
    "raw.aemo_nem_dispatch",
    "raw.aemo_wem_dispatch",
    "raw.openelectricity_responses",
    "raw.bom_observations",
]

# raw.* time-series tables eligible for the retention trim, keyed by
# their timestamp column (must match _SOURCE_COLUMNS in
# ecolens.ingestion.repository.raw_sync -- all 4 use "ts"). Deliberately
# excludes raw.aemo_holidays: reference data (~80 rows/yr), not a
# growth source, and dbt's dim_holiday needs a full calendar's worth.
RAW_RETENTION_TABLES: list[tuple[str, str]] = [
    ("raw.aemo_nem_dispatch", "ts"),
    ("raw.aemo_wem_dispatch", "ts"),
    ("raw.openelectricity_responses", "ts"),
    ("raw.bom_observations", "ts"),
]


class ArchiveManager:
    """Trims raw.* to a rolling retention window and VACUUMs the
    warehouse -- see the module docstring for the DuckDB-vs-Postgres
    distinction this stage relies on.
    """

    def __init__(self, settings: WarehouseRunnerSettings) -> None:
        self.settings = settings
        self._pg: Any = None

    def connect_pg(self) -> None:
        try:
            self._pg = psycopg2.connect(
                host=self.settings.pg_host,
                port=self.settings.pg_port,
                dbname=self.settings.pg_database,
                user=self.settings.pg_user,
                password=self.settings.pg_password,
            )
            # VACUUM cannot run inside a transaction block.
            self._pg.set_session(autocommit=True)
        except Exception as exc:  # noqa: BLE001
            log.warning("archive.pg_connect_failed", error=str(exc))
            self._pg = None

    def archive(self) -> StageResult:
        """Trim raw.* to `settings.raw_retention_days` -- see the module
        docstring. DuckDB (the permanent raw store) is never touched;
        this only prunes the Postgres working copy, which raw_sync can
        always rebuild via --full.
        """
        started = datetime.now(timezone.utc)
        if self._pg is None:
            return StageResult(
                name="archive",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=True,
                metrics={"status": "skipped", "reason": "postgres not connected"},
            )
        cutoff_days = self.settings.raw_retention_days
        deleted: dict[str, int] = {}
        try:
            cur = self._pg.cursor()
            for table, ts_col in RAW_RETENTION_TABLES:
                cur.execute(
                    f"delete from {table} where {ts_col} < now() - interval '{cutoff_days} days'"  # nosec B608
                )
                deleted[table] = cur.rowcount
                log.info("archive.trim_table", table=table, rows_deleted=cur.rowcount)
            cur.close()
        except Exception as exc:  # noqa: BLE001
            return StageResult(
                name="archive",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=str(exc),
            )
        return StageResult(
            name="archive",
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            success=True,
            rows_affected=sum(deleted.values()),
            metrics={"retention_days": cutoff_days, "rows_deleted": deleted},
        )

    def vacuum(self) -> StageResult:
        started = datetime.now(timezone.utc)
        if self._pg is None:
            return StageResult(
                name="vacuum",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=True,
                metrics={"status": "skipped", "reason": "postgres not connected"},
            )
        try:
            cur = self._pg.cursor()
            for table in VACUUM_TABLES:
                cur.execute(f"VACUUM ANALYZE {table}")
                log.info("vacuum.table", table=table)
            cur.close()
        except Exception as exc:  # noqa: BLE001
            return StageResult(
                name="vacuum",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=str(exc),
            )
        finished = datetime.now(timezone.utc)
        return StageResult(
            name="vacuum",
            started_at=started,
            finished_at=finished,
            success=True,
            metrics={"tables": VACUUM_TABLES},
        )

    def close(self) -> None:
        if self._pg is not None:
            self._pg.close()
            self._pg = None


__all__ = ["ArchiveManager", "VACUUM_TABLES"]
