"""`POST /v1/model/tune` / `GET /v1/model/tuning-runs` -- real
hyperparameter search, backing the dashboard's Training & Experiments
page's "Hyperparameter Tuning"/"Hparam Search History" tabs (root
TODO.md's "make every page fully functional with real data" -- both
were `IllustrativeBadge`-marked before this; `ml/tune.py`'s real grid
search was CLI-only, with no trigger route and no queryable trial
history).

Synchronous, not a 202-queued RabbitMQ trigger like `POST /v1/model/
train` -- `tune()`'s default grid (3 hidden_sizes × 2 learning_rates =
6 trials) genuinely completes in real seconds-to-low-minutes at this
service's current real data volume, so there's no separate worker
process to hand this off to the way incremental fine-tuning has one.
"""

from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class TuneTriggerRequest(AppBaseModel):
    regions: list[str] | None = None


class TuneTrialOut(AppBaseModel):
    hidden_size: int
    lr: float
    val_mape: float
    run_id: str


class TuneTriggerResponse(AppBaseModel):
    best_hidden_size: int
    best_lr: float
    best_val_mape: float
    best_run_id: str
    trials: list[TuneTrialOut]


class TuningRunOut(AppBaseModel):
    """One real MLflow run tagged `tuning=true` -- backs the Hparam
    Search History table. Same shape as `ExperimentOut`'s sibling
    `MlflowRunOut`, just pre-filtered to tuning trials."""

    run_id: str
    status: str
    started_at: datetime | None
    duration_seconds: float | None
    metrics: dict[str, float]
    params: dict[str, str]


class TuningRunsListResponse(AppBaseModel):
    data: list[TuningRunOut]
