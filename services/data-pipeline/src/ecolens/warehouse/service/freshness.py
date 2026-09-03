"""Stage 1: source freshness check.

Verifies that the DuckDB raw tables have fresh data. Compares each
source's most recent `fetched_at` against the configured freshness
threshold. If any source is stale, the run is aborted — running dbt on
stale data produces a stale warehouse.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ecolens.config import get_settings
from ecolens.ingestion.db import duckdb_store
from ecolens.shared.observability.logging import get_logger

from ecolens.warehouse.models.run_result import StageResult
from ecolens.warehouse.core.runner_settings import WarehouseRunnerSettings

log = get_logger(__name__)


class SourceFreshnessChecker:
    """Verify that the DuckDB raw tables have fresh data.

    Reads `Settings.historical_duckdb_path` -- the same path every
    ingestion write path uses -- rather than a warehouse-runner-specific
    duplicate (see settings.py's module docstring for why).
    """

    def __init__(self, settings: WarehouseRunnerSettings) -> None:
        self.settings = settings
        self._db_path: Path | None = None
        # (source, threshold) -- built from settings so overriding e.g.
        # freshness_threshold_aemo actually takes effect.
        self.sources: list[tuple[str, Any]] = [
            ("aemo_nem", settings.freshness_threshold_aemo),
            ("aemo_wem", settings.freshness_threshold_aemo),
            ("openelectricity", settings.freshness_threshold_aemo),
            ("bom", settings.freshness_threshold_bom),
            ("aemo_holidays", settings.freshness_threshold_holidays),
        ]

    def connect(self) -> None:
        path = get_settings().historical_duckdb_path.resolve()
        if not path.exists():
            log.warning("source_freshness.store_not_found", path=str(path))
            self._db_path = None
            return
        self._db_path = path
        log.info("source_freshness.connected", path=str(path))

    def close(self) -> None:
        self._db_path = None

    def check(self, *, allow_skip: bool = False) -> StageResult:
        """Check source freshness.

        Args:
            allow_skip: if True, treat "DuckDB store not found" as a
                soft success (used by --validate-only mode which is
                meant to run even before the store has ever been
                written to). Default False.
        """
        started = datetime.now(timezone.utc)
        if self._db_path is None:
            return StageResult(
                name="source_freshness",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=allow_skip,
                metrics={"status": "skipped", "reason": "duckdb store not found"},
                error=None
                if allow_skip
                else "DuckDB store not found; cannot verify sources",
            )
        try:
            return self._do_check(self._db_path)
        except Exception as exc:  # noqa: BLE001
            log.error("source_freshness.check_failed", error=str(exc))
            return StageResult(
                name="source_freshness",
                started_at=started,
                finished_at=datetime.now(timezone.utc),
                success=False,
                error=f"freshness check failed: {exc}",
            )

    def _do_check(self, db_path: Path) -> StageResult:
        started = datetime.now(timezone.utc)
        results: list[dict[str, Any]] = []
        all_fresh = True
        for source, threshold in self.sources:
            latest_ts = duckdb_store.latest_fetched_at(source, db_path=db_path)
            if latest_ts is None:
                all_fresh = False
                results.append(
                    {
                        "source": source,
                        "status": "missing",
                        "latest_ts": None,
                        "age_minutes": None,
                    }
                )
                continue
            if latest_ts.tzinfo is None:
                latest_ts = latest_ts.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - latest_ts
            is_fresh = age <= threshold
            if not is_fresh:
                all_fresh = False
            results.append(
                {
                    "source": source,
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
