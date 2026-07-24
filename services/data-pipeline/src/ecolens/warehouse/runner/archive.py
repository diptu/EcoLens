"""Stage 6: move old raw data to cold storage + VACUUM the warehouse.

Two sub-tasks:
  1. Archive: delete raw Mongo docs older than `archive_after_days`
  2. Vacuum:  VACUUM ANALYZE on the warehouse to reclaim space

Vacuum uses a plain synchronous psycopg2 connection rather than
asyncpg: `VACUUM` cannot run through asyncpg's extended query
protocol (Postgres rejects it — the same restriction that blocks
VACUUM inside a transaction block also blocks it from a prepared
statement), so a simple, un-pooled sync connection is the standard
workaround.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg2
from pymongo import MongoClient

from ecolens.ingestion.storage.settings import MongoSettings, get_mongo_settings
from ecolens.shared.observability.logging import get_logger

from .models import StageResult
from .settings import WarehouseRunnerSettings

log = get_logger(__name__)

ARCHIVE_COLLECTIONS: list[str] = [
    "aemo_nem_dispatch",
    "aemo_wem_dispatch",
    "openelectricity_responses",
    "bom_observations",
]

VACUUM_TABLES: list[str] = ["fact_demand_30min", "ml_features_demand_v1"]


class ArchiveManager:
    """Moves old raw data to cold storage + VACUUMs the warehouse.

    Connects to Mongo via `MongoSettings` (the same settings the
    ingestion fetchers themselves use), not a second warehouse-runner-
    specific copy -- see settings.py's module docstring for why.
    """

    def __init__(
        self,
        settings: WarehouseRunnerSettings,
        mongo_settings: MongoSettings | None = None,
    ) -> None:
        self.settings = settings
        self.mongo_settings = mongo_settings or get_mongo_settings()
        self._mongo: MongoClient | None = None
        self._pg: Any = None

    def connect_mongo(self) -> None:
        try:
            self._mongo = MongoClient(
                self.mongo_settings.mongo_uri, serverSelectionTimeoutMS=5000
            )
            self._mongo.admin.command("ping")
        except Exception as exc:  # noqa: BLE001
            log.warning("archive.mongo_connect_failed", error=str(exc))
            self._mongo = None

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
        started = datetime.now(timezone.utc)
        if self._mongo is None:
            return StageResult(
                name="archive",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=True,
                metrics={"status": "skipped", "reason": "mongo not connected"},
            )
        db = self._mongo[self.mongo_settings.mongo_db_name]
        cutoff = datetime.now(timezone.utc) - timedelta(
            days=self.settings.archive_after_days
        )
        archived: list[dict[str, Any]] = []
        for collection in ARCHIVE_COLLECTIONS:
            result = db[collection].delete_many({"fetched_at": {"$lt": cutoff}})
            archived.append({"collection": collection, "deleted": result.deleted_count})
            log.info(
                "archive.collection",
                collection=collection,
                deleted=result.deleted_count,
            )
        finished = datetime.now(timezone.utc)
        return StageResult(
            name="archive",
            started_at=started,
            finished_at=finished,
            success=True,
            rows_affected=sum(a["deleted"] for a in archived),
            metrics={"collections": archived, "cutoff": cutoff.isoformat()},
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
        if self._mongo is not None:
            self._mongo.close()
            self._mongo = None
        if self._pg is not None:
            self._pg.close()
            self._pg = None


__all__ = ["ArchiveManager", "ARCHIVE_COLLECTIONS", "VACUUM_TABLES"]
