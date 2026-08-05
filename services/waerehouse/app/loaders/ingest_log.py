"""Closes out a `"staged"` `meta._ingest_log` row once this service has
actually synced its data into Postgres `raw.*` — the consumer-side half
of the same audit trail `services/ingestion` starts (`ingest.run_started`
-> `"running"`, then `"staged"` once landed + published). Ported from
`data-pipeline`'s identical `pipeline.tasks._common.log_run_synced`/
`log_run_sync_failed`, relocated to the service that now actually owns
this responsibility.

`meta._ingest_log` is a table this service reads/writes but does not
own the schema for (`services/ingestion`'s own migrations create it) --
same relationship ingestion has to `raw.*` (writes-adjacent, doesn't own
the schema).
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def mark_synced(
    session: AsyncSession, run_id: uuid.UUID, rows_loaded: int
) -> None:
    """Close out a `"staged"` run as `"success"`. Only touches
    `finished_at`/`status`/`rows_loaded` -- `rows_landed`/
    `error_message`/`circuit_breaker_state` were already set by
    ingestion's own `_log_run_finish` at staging time and shouldn't be
    clobbered back to their defaults here.
    """
    await session.execute(
        text(
            """
            UPDATE meta._ingest_log
            SET finished_at = now(),
                status = 'success',
                rows_loaded = :rows_loaded
            WHERE id = :id
            """
        ),
        {"id": str(run_id), "rows_loaded": rows_loaded},
    )


async def mark_sync_failed(
    session: AsyncSession, run_id: uuid.UUID, error_message: str
) -> None:
    """Close out a `"staged"` run as `"sync_failed"` -- the data made it
    into DuckDB and the warehouse was notified, but the Postgres load
    itself failed. Distinct from plain `"failed"` (which means the fetch
    or staging step never got this far) so an operator can tell "retry
    the fetch" from "just retry the sync" apart at a glance in `meta.
    _ingest_log`."""
    await session.execute(
        text(
            """
            UPDATE meta._ingest_log
            SET finished_at = now(),
                status = 'sync_failed',
                error_message = :error_message
            WHERE id = :id
            """
        ),
        {"id": str(run_id), "error_message": error_message[:500]},
    )
