from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class TrainTriggerResponse(AppBaseModel):
    """202 -- publishes a `warehouse.transform.completed`-shaped RabbitMQ
    event (the same payload shape `services/waerehouse`'s
    `dbt.training_trigger.publish_training_trigger` builds after a
    successful dbt build), which `app.service.training_worker`'s
    consumer picks up and runs a real warm-started incremental fine-tune
    for. Not awaited before responding -- same "never run training
    inside a request/response cycle" invariant as the automatic path
    (see `service.training_worker`'s own module docstring). Ported from
    data-pipeline's identical schema.

    No `training_id`/`progress_url` to poll here -- the actual work
    happens in a separate, independently-running consumer process
    (`train-worker`) this API process has no in-process correlation id
    for. Poll `GET /v1/model/versions` for a new version to appear
    instead.
    """

    status: Literal["queued"] = "queued"
    queued_at: datetime
    regions: list[str]
    window_since: datetime
    window_until: datetime
    anomalies_flagged: int
    triggered_by: str
    architecture: str


class TrainingRunOut(AppBaseModel):
    """`GET /v1/model/training-runs` -- one `meta._training_log` row.
    `status == "running"` is the real "is a training run in flight right
    now" signal. Ported from data-pipeline's identical schema."""

    id: str
    model_name: str
    status: Literal["running", "success", "failed"]
    triggered_by: str
    regions: list[str]
    window_start: datetime
    window_end: datetime
    started_at: datetime
    finished_at: datetime | None = None
    run_id: str | None = None
    model_version: str | None = None
    error_message: str | None = None


class TrainingRunsListResponse(AppBaseModel):
    data: list[TrainingRunOut]
