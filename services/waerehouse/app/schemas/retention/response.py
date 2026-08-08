"""Response shapes for `GET /v1/retention/runs` -- real `meta._retention_log`
history backing the dashboard's Scheduled Operations row for the daily
export-and-prune-and-vacuum Celery Beat job (root `TODO.md`'s "Scheduled
Operations" item). Same shape/reasoning as `schemas/dbt/response.py`'s
`DbtBuildRunOut`/`DbtBuildRunsListResponse`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from app.schemas.base import AppBaseModel


class RetentionRunOut(AppBaseModel):
    """One `meta._retention_log` row."""

    id: str
    trigger: str
    triggered_by: str
    status: Literal["running", "success", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    pruned: dict[str, Any] | None = None
    vacuumed: list[str] | None = None
    error: str | None = None


class RetentionRunsListResponse(AppBaseModel):
    """`GET /v1/retention/runs` -- real `meta._retention_log` history,
    newest first."""

    data: list[RetentionRunOut]
