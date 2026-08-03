from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.base import AppBaseModel
from app.schemas.datasources.base import AuthType


class ScheduleUpdate(AppBaseModel):
    """`schedule` in the `PATCH /v1/data-sources/{id}` body — all optional,
    only the fields present are changed. `cron`/`timezone` are validated
    against the endpoint's regex/IANA-tz rules in
    `app.service.datasources.service`, not here, so a bad value maps to the
    spec's `invalid_cron`/`invalid_timezone` codes instead of a generic
    422."""

    cron: str | None = None
    timezone: str | None = None
    enabled: bool | None = None


class AuthUpdate(AppBaseModel):
    """Only `type` is changeable via PATCH — secrets stay in env vars."""

    type: AuthType


class PatchDataSourceRequest(AppBaseModel):
    schedule: ScheduleUpdate | None = None
    description: str | None = Field(default=None, max_length=500)
    auth: AuthUpdate | None = None
    metadata: dict[str, Any] | None = None


# ── §1.3 POST /v1/data-sources/{id}/run ──────────────────────────────────


class RunRequest(AppBaseModel):
    force: bool = False
    deduplicate: bool = True


# ── §1.4 POST /v1/data-sources/{id}/backfill ─────────────────────────────


class BackfillRequest(AppBaseModel):
    start: datetime
    end: datetime
    chunk: str = "P1D"
    concurrency: int = Field(default=1, ge=1, le=4)
    deduplicate: bool = True
