"""Stage 1: source freshness check.

Verifies that the MongoDB raw collections have fresh data. Compares
the latest document timestamp in each source collection against the
configured freshness threshold. If any source is stale, the run is
aborted — running dbt on stale data produces a stale warehouse.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from pymongo import MongoClient

from ecolens.ingestion.storage.settings import MongoSettings, get_mongo_settings
from ecolens.shared.observability.logging import get_logger

from .models import StageResult
from .settings import WarehouseRunnerSettings

log = get_logger(__name__)


class SourceFreshnessChecker:
    """Verify that the MongoDB raw collections have fresh data.

    Connects via `MongoSettings` (the same settings the ingestion
    fetchers themselves use), not a second warehouse-runner-specific
    copy -- see settings.py's module docstring for why.
    """

    def __init__(
        self,
        settings: WarehouseRunnerSettings,
        mongo_settings: MongoSettings | None = None,
    ) -> None:
        self.settings = settings
        self.mongo_settings = mongo_settings or get_mongo_settings()
        self._client: MongoClient | None = None
        # (collection, timestamp_field, threshold) -- built from settings so
        # overriding e.g. freshness_threshold_aemo actually takes effect.
        self.sources: list[tuple[str, str, Any]] = [
            ("aemo_nem_dispatch", "fetched_at", settings.freshness_threshold_aemo),
            ("aemo_wem_dispatch", "fetched_at", settings.freshness_threshold_aemo),
            (
                "openelectricity_responses",
                "fetched_at",
                settings.freshness_threshold_aemo,
            ),
            ("bom_observations", "fetched_at", settings.freshness_threshold_bom),
            (
                "aemo_holidays",
                "fetched_at",
                settings.freshness_threshold_holidays,
            ),
        ]

    def connect(self) -> None:
        try:
            self._client = MongoClient(
                self.mongo_settings.mongo_uri, serverSelectionTimeoutMS=5000
            )
            self._client.admin.command("ping")
            # Log only the host, never the full URI -- Mongo connection
            # strings carry credentials inline (mongodb+srv://user:pass@...).
            log.info(
                "source_freshness.connected",
                uri_host=urlparse(self.mongo_settings.mongo_uri).hostname,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("source_freshness.connect_failed", error=str(exc))
            self._client = None

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def check(self, *, allow_skip: bool = False) -> StageResult:
        """Check source freshness.

        Args:
            allow_skip: if True, treat "Mongo unavailable" as a soft
                success (used by --validate-only mode which is meant
                to run even when Mongo can't be reached). Default False.
        """
        started = datetime.now(timezone.utc)
        if self._client is None:
            return StageResult(
                name="source_freshness",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=allow_skip,
                metrics={"status": "skipped", "reason": "mongo not available"},
                error=None
                if allow_skip
                else "MongoDB unavailable; cannot verify sources",
            )
        try:
            return self._do_check(self._client)
        except Exception as exc:  # noqa: BLE001
            log.error("source_freshness.check_failed", error=str(exc))
            return StageResult(
                name="source_freshness",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=f"freshness check failed: {exc}",
            )

    def _do_check(self, client: MongoClient) -> StageResult:
        started = datetime.now(timezone.utc)
        db = client[self.mongo_settings.mongo_db_name]
        results: list[dict[str, Any]] = []
        all_fresh = True
        for collection, ts_field, threshold in self.sources:
            doc = db[collection].find_one(sort=[(ts_field, -1)])
            if doc is None:
                all_fresh = False
                results.append(
                    {
                        "collection": collection,
                        "status": "missing",
                        "latest_ts": None,
                        "age_minutes": None,
                    }
                )
                continue
            latest_ts = doc.get(ts_field)
            if latest_ts is None:
                all_fresh = False
                results.append(
                    {
                        "collection": collection,
                        "status": "no_ts_field",
                        "latest_ts": None,
                        "age_minutes": None,
                    }
                )
                continue
            if isinstance(latest_ts, str):
                latest_ts = datetime.fromisoformat(latest_ts.replace("Z", "+00:00"))
            if latest_ts.tzinfo is None:
                latest_ts = latest_ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - latest_ts
            is_fresh = age <= threshold
            if not is_fresh:
                all_fresh = False
            results.append(
                {
                    "collection": collection,
                    "status": "fresh" if is_fresh else "stale",
                    "latest_ts": latest_ts.isoformat(),
                    "age_minutes": round(age.total_seconds() / 60, 1),
                    "threshold_minutes": round(threshold.total_seconds() / 60, 1),
                }
            )
        finished = datetime.now(timezone.utc)
        log.info("source_freshness.check", fresh=all_fresh, sources=len(results))
        return StageResult(
            name="source_freshness",
            started_at=started,
            finished_at=finished,
            success=all_fresh,
            metrics={"sources": results, "all_fresh": all_fresh},
            error=None if all_fresh else "one or more sources are stale",
        )


__all__ = ["SourceFreshnessChecker"]
