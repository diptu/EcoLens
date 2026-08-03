from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class IngestRunSummary(AppBaseModel):
    run_id: str
    source: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    rows_loaded: int | None = None
    error: str | None = None
