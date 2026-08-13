from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class IngestionRunOut(AppBaseModel):
    """`GET /v1/ingestion/runs/{id}` — a single `meta._ingest_log` row,
    by its own run id (a real UUID `_common._log_run_start` generated),
    not scoped by catalog id/source the way `GET /v1/data-sources/{id}/
    history` is. Column shape matches the reconciled schema migration
    `0011_reconcile_ingest_schema.sql` created (`id`/`source`/`status`/
    `triggered_by`/`window_start`/`window_end`/`hostname`/`started_at`/
    `finished_at`/`rows_landed`/`rows_loaded`/`error_message`/
    `circuit_breaker_state`), plus two derived fields (`duration_ms`,
    `anomalies_flagged`) the same way `HistoryRun`/`LastRunInfo` already
    derive them elsewhere in this service.
    """

    id: str
    source: str
    status: str
    triggered_by: str
    window_start: str | None = None
    window_end: str | None = None
    hostname: str | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    rows_landed: int | None = None
    rows_loaded: int | None = None
    anomalies_flagged: int
    error_message: str | None = None
    circuit_breaker_state: str | None = None
