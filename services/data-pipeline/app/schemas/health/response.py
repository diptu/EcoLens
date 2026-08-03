from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel
from app.schemas.health.base import ComponentHealth, IngestSourceStatus, MLflowHealth


class HealthResponse(AppBaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(AppBaseModel):
    status: Literal["ready", "not_ready"]
    components: list[ComponentHealth]


class OpsStatus(AppBaseModel):
    db_healthy: bool
    mlflow: MLflowHealth
    last_ingest: list[IngestSourceStatus] = []
