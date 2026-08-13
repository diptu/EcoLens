"""Cloudflare R2 cold-storage export (README Phase 3 — "before pruning
data past the 2-month mark from NeonDB, configure a routine to dump
compressed historical partitions (Parquet/CSV) directly to Cloudflare R2
for long-term cold storage and auditing compliance without bloating
Postgres").

`export_and_prune` is the safe order this module exists to enforce:
export a table's about-to-be-pruned rows to a Parquet file in R2
*before* `retention.pruning` deletes them — never the other way around.
Each table's export is one Parquet file per prune run (not partitioned
further) under `{object_storage_coldstorage_prefix}/{table}/{cutoff
date}.parquet` — small enough at this service's real data volumes
(README's own free-tier framing) that per-run files are simpler than
managing partitioned writes, and idempotency-checked (`object_exists`)
the same way `services/ingestion`'s staged-run uploads already are, so
a retried prune run doesn't re-export/re-upload a file already there.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime, timedelta

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import coldstorage_export_rows_total
from app.db import object_storage
from app.db.session import get_session
from app.retention.pruning import _PRUNABLE_TABLES, _prune_table

log = get_logger(__name__)


def _export_key(table: str, cutoff: datetime) -> str:
    settings = get_settings()
    return (
        f"{settings.object_storage_coldstorage_prefix}/{table}/"
        f"before-{cutoff.date().isoformat()}.parquet"
    )


async def _fetch_rows_before(
    session: AsyncSession, table: str, column: str, cutoff: datetime
) -> pd.DataFrame:
    result = await session.execute(
        text(f'SELECT * FROM raw."{table}" WHERE "{column}" < :cutoff'),  # nosec B608 -- `table`/`column` always come from this module's own fixed `_PRUNABLE_TABLES` dict, never user input
        {"cutoff": cutoff},
    )
    rows = result.mappings().all()
    return pd.DataFrame(rows)


async def export_table(
    session: AsyncSession, table: str, column: str, cutoff: datetime
) -> str | None:
    """Export `table`'s rows older than `cutoff` to a Parquet file in R2.
    Returns the object key, or `None` if there was nothing to export
    (not an error — a table with no rows past the cutoff yet, or a
    retry after a key that already exists).
    """
    key = _export_key(table, cutoff)
    if await object_storage.object_exists(key):
        log.info("retention.coldstorage_export_skipped_already_present", key=key)
        return key

    df = await _fetch_rows_before(session, table, column, cutoff)
    if df.empty:
        return None

    buffer = io.BytesIO()
    df.to_parquet(buffer, engine="pyarrow", compression="snappy", index=False)
    await object_storage.upload_bytes(key, buffer.getvalue())
    coldstorage_export_rows_total.labels(table=table).inc(len(df))
    log.info("retention.coldstorage_exported", table=table, key=key, rows=len(df))
    return key


async def export_and_prune(days: int | None = None) -> dict[str, dict[str, int]]:
    """The safe, correct order README Phase 3 describes: export each
    prunable table's about-to-expire rows to R2 first, only delete them
    from Postgres once that export has actually succeeded (or already
    existed from an earlier attempt). A table whose export fails is
    simply *not* pruned this run — it'll be picked up again next time,
    rather than losing the only durable copy of data that failed to
    reach cold storage.

    Returns `{table: {"exported": n, "pruned": n}}` for whatever tables
    had anything to do.
    """
    settings = get_settings()
    window = days if days is not None else settings.retention_days
    cutoff = datetime.now(UTC) - timedelta(days=window)

    results: dict[str, dict[str, int]] = {}
    async with get_session() as session:
        for table, column in _PRUNABLE_TABLES.items():
            try:
                df = await _fetch_rows_before(session, table, column, cutoff)
                if df.empty:
                    continue

                key = await export_table(session, table, column, cutoff)
                if key is None:
                    continue

                rows_pruned = await _prune_table(session, table, column, cutoff)
                results[table] = {"exported": len(df), "pruned": rows_pruned}
            except Exception as exc:  # noqa: BLE001 - one table's export/prune failure must not stop the rest
                log.error(
                    "retention.export_and_prune_table_failed",
                    table=table,
                    error=str(exc),
                )

    if results:
        log.info(
            "retention.export_and_prune_completed",
            days=window,
            cutoff=cutoff.isoformat(),
            results=results,
        )
    return results
