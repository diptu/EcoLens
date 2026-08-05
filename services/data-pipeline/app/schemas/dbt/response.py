from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class DbtRunResponse(AppBaseModel):
    subcommand: str
    target: str
    exit_code: int


class DbtBuildRunOut(AppBaseModel):
    """`GET /v1/dbt/runs` -- one `meta._dbt_build_log` row (TODO.md's
    backfill section Follow-up item). See `dbt_build_log.py`'s module
    docstring for exactly which `run_dbt` call sites are logged here."""

    id: str
    subcommand: str
    target: str
    trigger: str
    triggered_by: str
    status: Literal["running", "success", "failed"]
    started_at: datetime
    finished_at: datetime | None = None
    exit_code: int | None = None
    error: str | None = None


class DbtBuildRunsListResponse(AppBaseModel):
    data: list[DbtBuildRunOut]
