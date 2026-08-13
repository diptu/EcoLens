"""Age-based retention for the shared `landed.duckdb` staging file
(`services/ingestion/TODO.md`'s Storage section — the file "now grows
forever by design (single file, appended); worth a real policy... before
local disk usage becomes a real operational problem").

**Policy**: a run's rows are only ever pruned once both of these are
true:

1. `meta._ingest_log.status = 'success'` — the warehouse-sync consumer
   has durably loaded this run's rows into Postgres `raw.*`. R2 already
   has its own durable copy earlier still (`duckdb_staging.upload_
   staged_file` runs *before* a run's status ever reaches `'staged'`,
   the precondition for `'success'`) — so `status = 'success'` alone
   already implies "both R2 and the warehouse have durable copies",
   exactly the precondition `TODO.md`'s own note describes.
2. `started_at` is older than `DEFAULT_RETENTION_DAYS` (a plain,
   easily-changed module constant, not a per-source/per-deployment
   config knob yet — deliberately simple to start with).

A `'staged'`/`'sync_failed'` run's rows are never touched — those are
exactly the runs `pipeline.duckdb_staging`'s own module docstring
already documents the shared file as the recovery artifact for.

**Manually/CLI-triggered** (`ecolens-ingestion prune-staging`), not on a
Celery Beat schedule — same conservative default `ml_anomaly`'s
retraining trigger uses, for the same reason: an operator/cron outside
this service decides when to run it, rather than silently deleting local
data on an unreviewed automatic schedule the first time this code ships.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.logging import get_logger
from app.db.session import get_session
from app.service.pipeline.duckdb_staging import delete_staged, staging_path
from app.service.pipeline.tasks.registry import SOURCES

log = get_logger(__name__)

# Deliberately generous starting point -- errs toward keeping local data
# around longer than strictly necessary rather than pruning too
# aggressively before this policy has seen real production use. Easy to
# tighten once actual disk usage/growth rate is observed.
#
# **Not the same number as R2's own retention, on purpose.** The real
# `ecolense` R2 bucket has its own lifecycle rule
# (`expire-staging-snapshots-60d`, applied 2026-08-07) expiring
# `staging/*` objects after 60 days -- double this constant's 30.
# Deliberate, not drift: R2 is the durable long-term artifact copy,
# this constant only governs the *local*, already-synced-to-Postgres
# scratch copy `duckdb_staging`'s own module docstring describes as a
# recovery artifact. A shorter local window and a longer R2 window are
# both the conservative direction to diverge in -- local rows are safe
# to prune once Postgres has them regardless of R2's own window, and
# R2 keeping its copy longer costs nothing local pruning depends on.
# If this number ever changes, the R2 rule is a separate, independent
# setting (Cloudflare dashboard, or the same `aioboto3`/R2-credentials
# path `app/service/object_storage.py` uses) -- not automatically kept
# in sync.
DEFAULT_RETENTION_DAYS = 30

# `meta._ingest_log.source` -> `duckdb_staging`'s table name -- the log
# only ever has the former, the shared file is keyed by the latter
# (`registry.SOURCES`' own `IngestSource.source`/`.table` split).
_TABLE_BY_LOG_SOURCE: dict[str, str] = {
    entry.source: entry.table for entry in SOURCES.values()
}


async def prune_synced_history(
    days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, int]:
    """Delete local DuckDB rows for every `'success'` run older than
    `days`. Returns `{source: rows_deleted}` for whatever actually had
    something to prune (sources with nothing eligible are omitted, not
    zero-valued) — `ecolens-ingestion prune-staging`'s own summary
    output.
    """
    cutoff = datetime.now(UTC) - timedelta(days=days)
    async with get_session() as session:
        result = await session.execute(
            text(
                "SELECT id, source FROM meta._ingest_log "
                "WHERE status = 'success' AND started_at < :cutoff"
            ),
            {"cutoff": cutoff},
        )
        eligible = result.fetchall()

    if not eligible:
        return {}

    path = str(staging_path())
    pruned: dict[str, int] = {}
    for run_id, log_source in eligible:
        table = _TABLE_BY_LOG_SOURCE.get(log_source)
        if table is None:
            # A `meta._ingest_log.source` value with no matching
            # `registry.SOURCES` entry -- e.g. legacy/renamed source.
            # Nothing local to prune for it; not this job's job to guess.
            continue
        rows_deleted = delete_staged(path, table, str(run_id))
        if rows_deleted:
            pruned[log_source] = pruned.get(log_source, 0) + rows_deleted

    if pruned:
        log.info(
            "retention.pruned_synced_history",
            days=days,
            cutoff=cutoff.isoformat(),
            pruned=pruned,
        )
    return pruned
