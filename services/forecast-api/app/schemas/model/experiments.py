"""`GET /v1/model/experiments`/`GET /v1/model/mlflow-runs` -- real MLflow
experiment/run listings backing the dashboard's Training & Experiments
page (`training/page.tsx`'s "Experiments" tab). See `app/service/mlops/
experiments.py`'s own docstring for why this is one shared experiment
across every architecture, not a per-model breakdown."""

from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class ExperimentOut(AppBaseModel):
    experiment_id: str
    name: str
    run_count: int
    last_run_at: datetime | None = None


class ExperimentsListResponse(AppBaseModel):
    data: list[ExperimentOut]


class MlflowRunOut(AppBaseModel):
    run_id: str
    experiment_name: str
    architecture: str | None = None
    status: str
    started_at: datetime | None = None
    duration_seconds: float | None = None
    metrics: dict[str, float] = {}


class MlflowRunsListResponse(AppBaseModel):
    data: list[MlflowRunOut]
