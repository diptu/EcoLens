"""Real MLflow experiments/runs listing -- backs the dashboard's
`training/page.tsx` "Experiments" tab, replacing `dashboards.
getMlflowExperiments()`/`getMlflowRuns()`'s fabricated sample data
(fake experiment names like `lstm_demand_v8_hptune`, `rf_baseline`,
`carbon_intensity_xgb` that don't correspond to anything real).

`tracking.configure_mlflow` points every training run in this service
(`ml/train.py`, `ml/train_tft.py`, `ml/train_energy_forecast.py`) at one
shared experiment (`tracking.EXPERIMENT_NAME = "lstm_demand"`, despite
the name, not just the demand-LSTM architecture) -- this is a thin,
real `MlflowClient.search_experiments`/`search_runs` wrapper, not a
per-architecture breakdown the way the old mock implied. A run's
`architecture` tag (set by `log_and_register_run`/
`log_and_register_energy_run`) is the real way to tell which model type
a given run trained.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from mlflow.tracking import MlflowClient

from app.core.config import Settings


@dataclass
class ExperimentSummary:
    experiment_id: str
    name: str
    run_count: int
    last_run_at: datetime | None


@dataclass
class MlflowRunSummary:
    run_id: str
    experiment_name: str
    architecture: str | None
    status: str
    started_at: datetime | None
    duration_seconds: float | None
    metrics: dict[str, float]


def _ms_to_datetime(ms: int | None) -> datetime | None:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def _list_experiments_sync(tracking_uri: str) -> list[ExperimentSummary]:
    client = MlflowClient(tracking_uri=tracking_uri)
    summaries = []
    for exp in client.search_experiments():
        runs = client.search_runs(
            [exp.experiment_id], order_by=["start_time DESC"], max_results=1000
        )
        summaries.append(
            ExperimentSummary(
                experiment_id=exp.experiment_id,
                name=exp.name,
                run_count=len(runs),
                last_run_at=_ms_to_datetime(runs[0].info.start_time) if runs else None,
            )
        )
    return summaries


def _list_runs_sync(tracking_uri: str, limit: int) -> list[MlflowRunSummary]:
    client = MlflowClient(tracking_uri=tracking_uri)
    experiments = client.search_experiments()
    if not experiments:
        return []
    exp_name_by_id = {exp.experiment_id: exp.name for exp in experiments}
    runs = client.search_runs(
        list(exp_name_by_id),
        order_by=["start_time DESC"],
        max_results=limit,
    )
    out = []
    for run in runs:
        start_ms = run.info.start_time
        end_ms = run.info.end_time
        out.append(
            MlflowRunSummary(
                run_id=run.info.run_id,
                experiment_name=exp_name_by_id.get(run.info.experiment_id, run.info.experiment_id),
                architecture=run.data.tags.get("architecture"),
                # `RunStatus` is already an uppercase string constant
                # ("FINISHED"/"RUNNING"/"FAILED"/"KILLED") -- lowercased
                # to match this dashboard's existing status-badge
                # convention (`TrainingRunLog.status`, model registry
                # stage badges, etc. are all lowercase).
                status=str(run.info.status).lower(),
                started_at=_ms_to_datetime(start_ms),
                duration_seconds=(end_ms - start_ms) / 1000 if start_ms and end_ms else None,
                metrics=dict(run.data.metrics),
            )
        )
    return out


async def list_experiments(settings: Settings) -> list[ExperimentSummary]:
    return await asyncio.to_thread(_list_experiments_sync, settings.mlflow_tracking_uri)


async def list_mlflow_runs(settings: Settings, limit: int = 8) -> list[MlflowRunSummary]:
    return await asyncio.to_thread(_list_runs_sync, settings.mlflow_tracking_uri, limit)
