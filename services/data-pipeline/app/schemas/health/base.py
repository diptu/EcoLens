from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class ComponentHealth(AppBaseModel):
    name: str
    healthy: bool
    detail: str | None = None


class MLflowHealth(AppBaseModel):
    """Populated by `app.service.mlops.health.run_health_check()` (ECO-D43).

    Until D43 lands, `/v1/readyz` only fills in `reachable`.
    """

    reachable: bool
    latest_run_id: str | None = None
    production_version: str | None = None


class IngestSourceStatus(AppBaseModel):
    source: str
    last_run_at: datetime | None = None
    last_status: str | None = None
