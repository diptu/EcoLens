"""Response shapes for `POST /v1/dbt/build`/`GET /v1/dbt/build/last` --
same field names as `data-pipeline`'s identical `app.schemas.dbt.response`
(that service's dashboard-facing dbt schemas), so the dashboard's
existing `DbtBuildTrigger`/`DbtBuildRunOut`-shaped TypeScript types keep
working unchanged when pointed at this service instead.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class DbtRunResponse(AppBaseModel):
    subcommand: str
    target: str
    exit_code: int


class DbtBuildRunOut(AppBaseModel):
    """One `meta._dbt_build_log` row."""

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
    """`GET /v1/dbt/build/runs` -- real `meta._dbt_build_log` history,
    newest first. A `status == "running"` row is the real "is a build in
    flight right now" signal -- distinct from (and a real persisted
    alternative to) the transient lock `_try_start_build` holds in the
    same table for the same duration."""

    data: list[DbtBuildRunOut]
