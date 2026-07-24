"""ECO-109: Training-Set Loader.

Reads `ml_features_demand_v1` -- the warehouse mart built by
`warehouse/dbt_project/models/marts/ml_features_demand_v1.sql` -- from
the warehouse Postgres and snapshots it to a versioned Parquet file, so
a training run always trains against a frozen point-in-time dataset
rather than a live table dbt might rebuild mid-run (see werehouse.md's
"ML features" layer).

Connects via `WarehouseApiSettings` (env prefix `WAREHOUSE_`) rather
than inventing a third copy of the warehouse Postgres connection
config -- the warehouse API and forecast-api's baseline forecaster
already read this exact database with their own independently-tuned
pools; this loader is a third, batch-shaped reader of the same data,
not a different database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import asyncpg
import pandas as pd

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger
from ecolens.warehouse.api.settings import (
    WarehouseApiSettings,
    get_warehouse_api_settings,
)

log = get_logger(__name__)

_QUERY = "select * from ml_features_demand_v1 {where} order by region, ts_30"


@dataclass(frozen=True)
class TrainingSnapshot:
    """A frozen, on-disk copy of ml_features_demand_v1 as of `created_at`."""

    path: Path
    row_count: int
    regions: tuple[str, ...]
    created_at: datetime


class TrainingSetLoader:
    """Reads ml_features_demand_v1 and snapshots it to Parquet."""

    def __init__(
        self,
        warehouse_settings: WarehouseApiSettings | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.warehouse_settings = warehouse_settings or get_warehouse_api_settings()
        self.settings = settings or get_settings()

    async def fetch(
        self,
        regions: tuple[str, ...] | None = None,
        *,
        since: date | datetime | None = None,
        until: date | datetime | None = None,
    ) -> pd.DataFrame:
        """Reads the feature table, optionally scoped to `[since, until)`
        (both ends optional, `until` exclusive) -- the one piece needed
        to pull just *one chunk* (e.g. one calendar year) for
        `training/incremental.py`'s chunked training loop, rather than
        always reading the whole table.
        """
        ws = self.warehouse_settings
        if ws.pg_dsn:
            conn = await asyncpg.connect(
                dsn=ws.pg_dsn, timeout=ws.pg_command_timeout_seconds
            )
        else:
            conn = await asyncpg.connect(
                host=ws.pg_host,
                port=ws.pg_port,
                database=ws.pg_database,
                user=ws.pg_user,
                password=ws.pg_password,
                timeout=ws.pg_command_timeout_seconds,
            )
        try:
            clauses = []
            params: list[object] = []
            if regions:
                params.append(list(regions))
                clauses.append(f"region = any(${len(params)}::text[])")
            if since is not None:
                params.append(since)
                clauses.append(f"ts_30 >= ${len(params)}")
            if until is not None:
                params.append(until)
                clauses.append(f"ts_30 < ${len(params)}")
            where = f"where {' and '.join(clauses)}" if clauses else ""
            query = _QUERY.format(where=where)
            rows = await conn.fetch(query, *params)
        finally:
            await conn.close()

        log.info(
            "training.fetched",
            rows=len(rows),
            regions=regions,
            since=since.isoformat() if since else None,
            until=until.isoformat() if until else None,
        )
        return pd.DataFrame(dict(r) for r in rows)

    async def snapshot(
        self, regions: tuple[str, ...] | None = None
    ) -> TrainingSnapshot:
        """Fetch + write a versioned Parquet snapshot. Returns its metadata."""
        df = await self.fetch(regions)
        snap_dir = self.settings.training_snapshot_dir
        snap_dir.mkdir(parents=True, exist_ok=True)

        created_at = datetime.now(timezone.utc)
        path = snap_dir / f"ml_features_demand_v1_{created_at:%Y%m%dT%H%M%SZ}.parquet"
        df.to_parquet(path, index=False)

        regions_found = tuple(sorted(df["region"].unique())) if len(df) else ()
        log.info(
            "training.snapshot_written",
            path=str(path),
            rows=len(df),
            regions=regions_found,
        )
        return TrainingSnapshot(
            path=path,
            row_count=len(df),
            regions=regions_found,
            created_at=created_at,
        )


def load_snapshot(path: Path) -> pd.DataFrame:
    """Reads a previously-written snapshot back into a DataFrame."""
    return pd.read_parquet(path)


def latest_snapshot(snapshot_dir: Path) -> Path | None:
    """Most recently written snapshot in `snapshot_dir`, or None if empty."""
    candidates = sorted(snapshot_dir.glob("ml_features_demand_v1_*.parquet"))
    return candidates[-1] if candidates else None


__all__ = [
    "TrainingSetLoader",
    "TrainingSnapshot",
    "load_snapshot",
    "latest_snapshot",
]
