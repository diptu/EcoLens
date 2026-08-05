"""`GET /v1/ingestion/runs/{id}` logic — look up a single `meta.
_ingest_log` row by its own run id (a UUID `_common._log_run_start`
generated), not scoped by catalog id/source the way `app.service.
datasources.monitoring.get_source_history` is.
"""

from __future__ import annotations

import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ApiError
from app.schemas.ingest import IngestionRunOut

_COLUMNS = (
    "id, source, status, triggered_by, window_start, window_end, hostname, "
    "started_at, finished_at, rows_landed, rows_loaded, error_message, "
    "circuit_breaker_state"
)


async def get_ingest_run(db: AsyncSession, run_id: uuid.UUID) -> IngestionRunOut:
    result = await db.execute(
        text(f"SELECT {_COLUMNS} FROM meta._ingest_log WHERE id = :id"),  # nosec B608 -- `_COLUMNS` is a fixed module-level constant, not user input
        {"id": str(run_id)},
    )
    row = result.mappings().first()
    if row is None:
        raise ApiError(404, "not_found", f"No ingestion run with id '{run_id}'")

    anomalies_result = await db.execute(
        text("SELECT count(*) FROM meta.anomalies WHERE run_id = :run_id"),
        {"run_id": str(run_id)},
    )
    anomalies_flagged = int(anomalies_result.scalar() or 0)

    duration_ms = None
    if row["finished_at"] is not None:
        duration_ms = round(
            (row["finished_at"] - row["started_at"]).total_seconds() * 1000
        )

    return IngestionRunOut(
        id=str(row["id"]),
        source=row["source"],
        status=row["status"],
        triggered_by=row["triggered_by"],
        window_start=row["window_start"],
        window_end=row["window_end"],
        hostname=row["hostname"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        duration_ms=duration_ms,
        rows_landed=row["rows_landed"],
        rows_loaded=row["rows_loaded"],
        anomalies_flagged=anomalies_flagged,
        error_message=row["error_message"],
        circuit_breaker_state=row["circuit_breaker_state"],
    )
