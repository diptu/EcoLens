from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel
from app.schemas.datasources.base import (
    AuthInfo,
    Category,
    HealthInfo,
    LastRunInfo,
    ScheduleInfo,
)


class DataSourceOut(AppBaseModel):
    id: str
    name: str
    category: Category
    description: str
    url: str
    license: str
    auth: AuthInfo
    schedule: ScheduleInfo
    health: HealthInfo
    last_run: LastRunInfo | None = None
    regions: list[str]
    metadata: dict[str, object]
    version: int
    created_at: datetime
    updated_at: datetime
