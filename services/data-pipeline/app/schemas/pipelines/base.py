from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel

PipelineStatus = Literal["active", "paused"]
Trigger = Literal["schedule", "manual", "backfill", "retry", "dependency"]


class PipelineScheduleInfo(AppBaseModel):
    cron: str
    timezone: str
    enabled: bool
