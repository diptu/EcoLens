"""Stage 6: VACUUM the warehouse.

Historically this stage also deleted raw Mongo docs older than
`archive_after_days` -- the idea being that DuckDB held a durable
"cold storage" backup, so the live Mongo cluster didn't need to keep
years of raw history forever. Now that DuckDB is the sole raw store
(no separate live cluster to prune "old" data away from -- see
TODO.md's ECO-150..158 for that migration), there's nothing left to
archive: deleting old DuckDB rows would just destroy data with no
backup, the exact failure mode ECO-150..157 existed to prevent in the
first place. `archive()` is kept as a documented no-op (rather than
removed outright) so `WarehouseRunner`'s Stage 6 slot and
`RunResult.stages` shape don't change.

Vacuum uses a plain synchronous psycopg2 connection rather than
asyncpg: `VACUUM` cannot run through asyncpg's extended query
protocol (Postgres rejects it — the same restriction that blocks
VACUUM inside a transaction block also blocks it from a prepared
statement), so a simple, un-pooled sync connection is the standard
workaround.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import psycopg2

from ecolens.shared.observability.logging import get_logger

from .models import StageResult
from .settings import WarehouseRunnerSettings

log = get_logger(__name__)

VACUUM_TABLES: list[str] = ["fact_demand_30min", "ml_features_demand_v1"]


class ArchiveManager:
    """VACUUMs the warehouse. `archive()` is a documented no-op -- see
    the module docstring for why there's no longer anything to archive.
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
        """No-op -- see the module docstring. DuckDB is the permanent
        raw store now; there's no separate live cluster to prune old
        data away from, and no cold-storage backup to prune *into*.
        """
        started = datetime.now(timezone.utc)
        return StageResult(
            name="archive",
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            success=True,
            metrics={
                "status": "skipped",
                "reason": "no-op: DuckDB is the permanent raw store, nothing to archive",
            },
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
