"""`GET /v1/model` — currently-served model metadata (`README.md` § API
reference). `GET /v1/model/versions` — every registered version, any
stage (Model Operations TODO.md Phase 1). `POST /v1/model/versions/
{version}/promote` — real, gated stage transitions (Phase 3).
`DELETE /v1/model/versions/{version}` — real, gated registry-entry
removal (2026-08-05); refuses the current Production version.

`POST /v1/model/train`/`GET /v1/model/training-runs` — moved here from
data-pipeline as part of the training-code migration (deliberately open,
no auth required, same reasoning as `/v1/data-sources/{id}/run`/
`/backfill` had in that service: triggering work isn't a privileged
action in this platform's current scope)."""

from __future__ import annotations

import math

from fastapi import APIRouter, Depends, Query
from mlflow.exceptions import MlflowException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_app_settings, get_db, get_model_registry
from app.core.errors import ApiError
from app.schemas.model import (
    DriftListResponse,
    DriftReportOut,
    EvaluationSummaryOut,
    ExperimentOut,
    ExperimentsListResponse,
    LossCurveOut,
    LossCurvePointOut,
    MlflowRunOut,
    MlflowRunsListResponse,
    ModelInfo,
    ModelVersionOut,
    ModelVersionsListResponse,
    PromoteModelRequest,
    RegionEvaluationOut,
    TrainingRunsListResponse,
    TrainRequest,
    TrainTriggerResponse,
    TuneTrialOut,
    TuneTriggerRequest,
    TuneTriggerResponse,
    TuningRunOut,
    TuningRunsListResponse,
)
from app.core.config import Settings
from app.service.model.actions import list_training_runs, trigger_training
from app.service.mlops.experiments import list_experiments, list_mlflow_runs, list_tuning_runs
from app.service.mlops.live_drift import compute_drift
from app.service.ml.registry import (
    DeletionRejected,
    ModelRegistry,
    PromotionRejected,
    delete_model_version,
    get_latest_evaluation,
    get_loss_curve,
    list_versions,
    promote_version,
)

router = APIRouter(prefix="/v1", tags=["model"])


@router.post("/model/train", response_model=TrainTriggerResponse, status_code=202)
async def trigger_training_endpoint(
    body: TrainRequest = TrainRequest(),
) -> TrainTriggerResponse:
    return await trigger_training(
        body.regions, body.window_hours, triggered_by="public"
    )


@router.get("/model/training-runs", response_model=TrainingRunsListResponse)
async def get_training_runs(
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> TrainingRunsListResponse:
    runs = await list_training_runs(db, limit)
    return TrainingRunsListResponse(data=runs)


@router.post("/model/tune", response_model=TuneTriggerResponse)
async def trigger_tune_endpoint(
    body: TuneTriggerRequest = TuneTriggerRequest(),
    settings: Settings = Depends(get_app_settings),
) -> TuneTriggerResponse:
    """Real grid search (`ml/tune.py`'s own default grid: 3 hidden_sizes
    × 2 learning_rates = 6 trials, each a full `train_model` run) --
    root TODO.md's "Hyperparameter Tuning tab" item, previously
    `IllustrativeBadge`-marked because this trigger route didn't exist
    (the search itself was always real, CLI-only). Synchronous, not
    202-queued -- see this schema's own module docstring for why (no
    separate worker process this hands off to, and the real grid
    completes in real seconds-to-low-minutes at this service's current
    data volume)."""
    from app.service.ml.tune import tune

    regions = body.regions or settings.model_default_regions
    result = await tune(regions, settings=settings)
    return TuneTriggerResponse(
        best_hidden_size=result.best_config.hidden_size,
        best_lr=result.best_config.lr,
        best_val_mape=result.best_val_mape,
        best_run_id=result.best_run_id,
        trials=[
            TuneTrialOut(
                hidden_size=t.hidden_size, lr=t.lr, val_mape=t.val_mape, run_id=t.run_id
            )
            for t in result.trials
        ],
    )


@router.get("/model/tuning-runs", response_model=TuningRunsListResponse)
async def get_tuning_runs(
    limit: int = Query(default=20, ge=1, le=200),
    settings: Settings = Depends(get_app_settings),
) -> TuningRunsListResponse:
    """Real MLflow runs tagged `tuning=true` -- root TODO.md's "Hparam
    Search History table" item, previously 4 hardcoded sample rows."""
    runs = await list_tuning_runs(settings, limit)
    return TuningRunsListResponse(
        data=[
            TuningRunOut(
                run_id=r.run_id,
                status=r.status,
                started_at=r.started_at,
                duration_seconds=r.duration_seconds,
                metrics=r.metrics,
                params=r.params,
            )
            for r in runs
        ]
    )


@router.get("/model/experiments", response_model=ExperimentsListResponse)
async def get_experiments(
    settings: Settings = Depends(get_app_settings),
) -> ExperimentsListResponse:
    """Real MLflow experiments (`service/mlops/experiments.py`) --
    backs the dashboard's Training & Experiments page. Every
    architecture this service trains logs to one shared experiment
    (`mlops.tracking.EXPERIMENT_NAME`), so this is typically a
    single-row list, not a per-model breakdown -- see that module's own
    docstring."""
    experiments = await list_experiments(settings)
    return ExperimentsListResponse(
        data=[
            ExperimentOut(
                experiment_id=e.experiment_id,
                name=e.name,
                run_count=e.run_count,
                last_run_at=e.last_run_at,
            )
            for e in experiments
        ]
    )


@router.get("/model/mlflow-runs", response_model=MlflowRunsListResponse)
async def get_mlflow_runs(
    limit: int = Query(default=8, ge=1, le=50),
    settings: Settings = Depends(get_app_settings),
) -> MlflowRunsListResponse:
    """Real recent MLflow runs across every experiment, newest first --
    `architecture` comes from each run's own tag (set by
    `log_and_register_run`/`log_and_register_energy_run`/
    `train_tft.py`'s equivalent), so a caller can tell LSTM/TFT/
    energy-forecast runs apart even though they share one experiment."""
    runs = await list_mlflow_runs(settings, limit)
    return MlflowRunsListResponse(
        data=[
            MlflowRunOut(
                run_id=r.run_id,
                experiment_name=r.experiment_name,
                architecture=r.architecture,
                status=r.status,
                started_at=r.started_at,
                duration_seconds=r.duration_seconds,
                metrics=r.metrics,
            )
            for r in runs
        ]
    )


def _none_if_nan(value: float) -> float | None:
    return None if math.isnan(value) else value


@router.get("/model/drift", response_model=DriftListResponse)
async def get_model_drift(
    model_name: str | None = None,
    region: list[str] | None = Query(default=None),
    settings: Settings = Depends(get_app_settings),
) -> DriftListResponse:
    """Real per-feature PSI/KS drift (`mlops/live_drift.py`) -- top 10
    features by PSI between an older and a more recent slice of the same
    real training data. `[]` when there isn't enough real data on both
    sides yet (this environment's empty Postgres marts for `lstm_demand`/
    `lstm_demand_tft` today) -- a real, expected state, not an error.
    See `live_drift.py`'s own docstring for the real, disclosed
    limitation this comparison has (chronological split of one dataset,
    not training-vs-live-serving)."""
    model_name = model_name or settings.mlflow_registry_model_name
    regions = region or settings.model_default_regions
    reports = await compute_drift(model_name, regions)
    return DriftListResponse(
        data=[
            DriftReportOut(
                feature=r.feature,
                psi=_none_if_nan(r.psi),
                psi_severity=r.psi_severity,
                ks_statistic=_none_if_nan(r.ks_statistic),
                ks_pvalue=_none_if_nan(r.ks_pvalue),
                reference_n=r.reference_n,
                comparison_n=r.comparison_n,
            )
            for r in reports
        ]
    )


def _registry_error(exc: MlflowException, *, not_found_message: str) -> ApiError:
    """Maps an `MlflowException` to the right HTTP status -- MLflow sets
    a real `error_code` per failure kind (confirmed against a live
    tracking server: a bad model/version name raises with
    `RESOURCE_DOES_NOT_EXIST`, an auth/connectivity failure raises with
    `PERMISSION_DENIED`/`INTERNAL_ERROR`/etc). Only the former is
    genuinely "not found" -- collapsing every `MlflowException` into 404
    (an earlier version of this code did exactly that) would mislabel a
    registry that's unreachable or misconfigured as "the version doesn't
    exist", which is a different, more actionable problem for whoever's
    debugging it."""
    if exc.error_code == "RESOURCE_DOES_NOT_EXIST":
        return ApiError(404, "not_found", not_found_message)
    return ApiError(503, "registry_unavailable", str(exc))


@router.get("/model", response_model=ModelInfo)
async def get_model_info(
    registry: ModelRegistry = Depends(get_model_registry),
    settings: Settings = Depends(get_app_settings),
) -> ModelInfo:
    bundle = registry.bundle
    if bundle is None:
        return ModelInfo(status="not_loaded", name=settings.mlflow_registry_model_name)
    return ModelInfo(
        status="loaded",
        name=settings.mlflow_registry_model_name,
        version=bundle.version,
        stage=bundle.stage,
        run_id=bundle.run_id,
        loaded_at=bundle.loaded_at,
        git_sha=bundle.git_sha,
        horizon=bundle.horizon,
        lookback=bundle.lookback,
        metrics=bundle.metrics,
    )


@router.get("/model/versions", response_model=ModelVersionsListResponse)
async def get_model_versions(
    model_name: str | None = None,
    settings: Settings = Depends(get_app_settings),
) -> ModelVersionsListResponse:
    """`model_name` (`todo-model-training.md` Phase 8: dashboard
    experiment-comparison view) — defaults to `Settings.
    mlflow_registry_model_name` (`lstm_demand`) unchanged for existing
    callers, but a caller can pass e.g. `?model_name=lstm_demand_tft` to
    list the TFT registry's own versions instead -- the real, minimal
    change needed to let the dashboard fetch and compare more than one
    architecture's registry, without a new endpoint (this one was
    already architecture-agnostic internally; it just hardcoded which
    architecture)."""
    model_name = model_name or settings.mlflow_registry_model_name
    try:
        versions = await list_versions(model_name)
    except MlflowException as exc:
        raise _registry_error(
            exc, not_found_message=f"No registered model '{model_name}'"
        ) from exc
    return ModelVersionsListResponse(
        name=model_name,
        data=[
            ModelVersionOut(
                version=v.version,
                stage=v.stage,
                run_id=v.run_id,
                created_at=v.created_at,
                metrics=v.metrics,
                git_sha=v.git_sha,
            )
            for v in versions
        ],
    )


@router.get("/model/versions/{version}/loss-curve", response_model=LossCurveOut)
async def get_model_version_loss_curve(
    version: str,
    model_name: str | None = None,
    settings: Settings = Depends(get_app_settings),
) -> LossCurveOut:
    """Real per-epoch `train_loss`/`val_mape` history for one version --
    read from MLflow's step-metric history (`ml/registry.py`'s
    `get_loss_curve`), not the single final value `GET /model/versions`
    exposes via `ModelVersionOut.metrics`. `points` is `[]` for a version
    trained before per-epoch logging existed -- a real, expected state,
    not an error."""
    model_name = model_name or settings.mlflow_registry_model_name
    try:
        curve = await get_loss_curve(model_name, version)
    except MlflowException as exc:
        raise _registry_error(
            exc, not_found_message=f"No version '{version}' of '{model_name}'"
        ) from exc
    return LossCurveOut(
        model_name=model_name,
        version=version,
        run_id=curve.run_id,
        points=[
            LossCurvePointOut(
                epoch=p.epoch,
                train_loss=p.train_loss,
                val_loss=p.val_loss,
                val_mape=p.val_mape,
                val_rmse=p.val_rmse,
                val_mae=p.val_mae,
            )
            for p in curve.points
        ],
    )


@router.get(
    "/model/versions/{version}/evaluation", response_model=EvaluationSummaryOut | None
)
async def get_model_version_evaluation(
    version: str,
    model_name: str | None = None,
    settings: Settings = Depends(get_app_settings),
) -> EvaluationSummaryOut | None:
    """Real walk-forward backtest results (`ecolens-forecast evaluate`)
    for one version, per region/candidate -- `null` (not a 404) when no
    evaluation has ever been run for it, same "empty is a real, expected
    state" convention `GET /v1/model/drift` etc. already use. Distinct
    from `GET /model/versions`' own `metrics.test_mape` (the easier,
    training-time split) -- this is the honest, harder rolling-origin
    backtest against a real seasonal-naive baseline (`ml/registry.py`'s
    `get_latest_evaluation` docstring has the full reasoning for why
    these live in a separate MLflow run and can't be merged into the
    version's own metrics)."""
    model_name = model_name or settings.mlflow_registry_model_name
    summary = await get_latest_evaluation(model_name, version)
    if summary is None:
        return None
    return EvaluationSummaryOut(
        model_name=model_name,
        version=version,
        run_id=summary.run_id,
        evaluated_at=summary.evaluated_at,
        n_origins=summary.n_origins,
        regions=[
            RegionEvaluationOut(
                region=r.region,
                candidate=r.candidate,
                mape=r.mape,
                rmse=r.rmse,
                coverage=r.coverage,
                n_origins=r.n_origins,
            )
            for r in summary.regions
        ],
    )


@router.post("/model/versions/{version}/promote", response_model=ModelVersionOut)
async def promote_model_version(
    version: str,
    body: PromoteModelRequest,
    settings: Settings = Depends(get_app_settings),
) -> ModelVersionOut:
    model_name = body.model_name or settings.mlflow_registry_model_name
    try:
        summary = await promote_version(model_name, version, body.stage, force=body.force)
    except PromotionRejected as exc:
        raise ApiError(409, "worse_than_production", exc.message) from exc
    except MlflowException as exc:
        raise _registry_error(
            exc, not_found_message=f"No version '{version}' of '{model_name}'"
        ) from exc

    return ModelVersionOut(
        version=summary.version,
        stage=summary.stage,
        run_id=summary.run_id,
        created_at=summary.created_at,
        metrics=summary.metrics,
        git_sha=summary.git_sha,
    )


@router.delete("/model/versions/{version}", status_code=204)
async def delete_model_version_route(
    version: str,
    model_name: str | None = None,
    settings: Settings = Depends(get_app_settings),
) -> None:
    """Permanently removes `version` from the MLflow registry -- the
    underlying training run/artifacts are untouched, only the registry
    entry pointing at it (see `ml/registry.py`'s `delete_model_version`
    for why). Refuses to delete the current Production version (409) --
    that's what `forecast-api` is actually serving live traffic from."""
    model_name = model_name or settings.mlflow_registry_model_name
    try:
        await delete_model_version(model_name, version)
    except DeletionRejected as exc:
        raise ApiError(409, "is_production", exc.message) from exc
    except MlflowException as exc:
        raise _registry_error(
            exc, not_found_message=f"No version '{version}' of '{model_name}'"
        ) from exc
