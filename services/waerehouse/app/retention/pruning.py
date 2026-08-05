"""Rolling-window retention (README Phase 3 — "Critical for Free Tier"):
"a daily automated cleanup script that safely deletes raw and curated
records older than 60 days".

Targets the 4 real time-series `raw.*` tables (`ts`-keyed, per `app.
migrations.0002_fix_raw_schema_to_match_real_ingestion_output`) —
`aemo_holidays` is deliberately excluded, same reasoning `services/
ingestion`'s own ML training/backfill already applies to it: it's an
annual snapshot, not a per-source time series, and isn't a real
candidate for a 60-day rolling window.

**Curated (dbt marts) retention is a documented follow-up, not
implemented here** — this pass focuses on `raw.*`, the table set this
service's own migration just established real ownership of; the marts
schema's own retention needs (which tables, what natural key) weren't
researched as part of this change and deserve their own pass rather
than a rushed guess.

**Manually/cron-triggered** (`ecolens-warehouse prune`), not a
background scheduler baked into this service — same conservative
default `services/ingestion`'s own `retention.py`/`ml_anomaly.py`
established this session: an operator/cron outside the service decides
when a destructive delete actually runs, rather than it shipping with
an unreviewed automatic schedule from day one. README's own "pg_cron or
Celery Task" framing already treats this as "some external scheduler
calls in", not "the service schedules itself" — a plain CLI entrypoint
is the simplest thing that satisfies that.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import retention_rows_pruned_total
from app.db.session import get_session

log = get_logger(__name__)

# `table -> its own timestamp column`. All 4 have that column as the
# leading part of their `PRIMARY KEY`, so a `WHERE <col> < :cutoff`
# delete is already index-backed -- no extra index needed (see the
# schema migration's own header note).
_PRUNABLE_TABLES: dict[str, str] = {
    "aemo_nem_dispatch": "ts",
    "aemo_wem_dispatch": "ts",
    "bom_observations": "ts",
    "openelectricity_mix": "ts",
}


async def _prune_table(
    session: AsyncSession, table: str, column: str, cutoff: datetime
) -> int:
    result = await session.execute(
        text(f'DELETE FROM raw."{table}" WHERE "{column}" < :cutoff'),  # nosec B608 -- `table`/`column` always come from this module's own fixed `_PRUNABLE_TABLES` dict, never user input
        {"cutoff": cutoff},
    )
    # `AsyncSession.execute()` is typed as the generic `Result[Any]`,
    # which doesn't statically expose `.rowcount` -- at runtime a DML
    # statement (this DELETE) always returns the `CursorResult` subclass
    # that does. Real, narrow mismatch between the static type and the
    # actual runtime type here, not a genuine type error.
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def prune_raw_tables(days: int | None = None) -> dict[str, int]:
    """Delete rows older than `days` (default `Settings.retention_days`,
    60) from every prunable `raw.*` table. Returns `{table: rows_
    deleted}` for whatever actually had something to prune (tables with
    nothing eligible are omitted, not zero-valued).
    """
    settings = get_settings()
    window = days if days is not None else settings.retention_days
    cutoff = datetime.now(UTC) - timedelta(days=window)

    pruned: dict[str, int] = {}
    async with get_session() as session:
        for table, column in _PRUNABLE_TABLES.items():
            rows_deleted = await _prune_table(session, table, column, cutoff)
            if rows_deleted:
                pruned[table] = rows_deleted
                retention_rows_pruned_total.labels(table=table).inc(rows_deleted)

    if pruned:
        log.info(
            "retention.pruned_raw_tables",
            days=window,
            cutoff=cutoff.isoformat(),
            pruned=pruned,
        )
    return pruned
