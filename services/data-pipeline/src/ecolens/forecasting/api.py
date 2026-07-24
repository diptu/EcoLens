"""ECO-118 (part 2): the internal control surface for the forecasting
pipeline -- trigger-train, trigger-evaluate, model-status. A plain
`APIRouter` (same shape as `ingestion.api`'s own router), meant to be
mounted on data-pipeline's own control API (`ecolens.api.app`), not a
public contract -- `forecast-api` never calls this, it only ever reads
the MLflow registry (`strategy.md` §2).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from ecolens.config import get_settings
from ecolens.shared.job_tracker import JobTracker
from ecolens.shared.observability.logging import get_logger

from .data import TrainingSetLoader
from .evaluation.evaluate import evaluate_model, log_evaluation_to_mlflow
from .features import build_windowed_dataset
from .mlops.health import get_health_snapshot
from .mlops.promote import promote_if_better
from .mlops.registry import ModelRegistry

log = get_logger(__name__)

router = APIRouter(prefix="/forecasting", tags=["forecasting"])

_jobs = JobTracker()


async def _run_training_job() -> None:
    """train -> evaluate -> register -> promote-if-better, in one shot.
    This is the weekly-full-retrain path (ECO-119's cron cadence).
    """
    from .training.train import (
        train_model,
    )  # local import: avoid torch/mlflow import cost on every app boot

    settings = get_settings()
    df = await TrainingSetLoader(settings=settings).fetch()
    dataset = build_windowed_dataset(
        df, lookback=settings.model_lookback, horizon=settings.model_horizon
    )
    result = train_model(dataset, settings=settings)
    evaluation = evaluate_model(result.model, dataset, alpha=settings.conformal_alpha)
    log_evaluation_to_mlflow(evaluation, run_id=result.run_id, settings=settings)

    registry = ModelRegistry(settings=settings)
    registered = registry.register(result.run_id)
    promote_if_better(
        registry, registered, evaluation, alias=settings.model_registry_alias
    )


async def _run_evaluation_job() -> None:
    """Re-scores the *current production* model against a fresh snapshot
    -- distinct from training's own built-in evaluate, which scores a
    freshly trained model against its own snapshot's test split. This
    is how live drift in model accuracy gets tracked between retrains.
    """
    settings = get_settings()
    registry = ModelRegistry(settings=settings)
    model = registry.load_by_alias(settings.model_registry_alias)

    df = await TrainingSetLoader(settings=settings).fetch()
    dataset = build_windowed_dataset(
        df, lookback=settings.model_lookback, horizon=settings.model_horizon
    )
    evaluation = evaluate_model(model, dataset, alpha=settings.conformal_alpha)

    current = registry.get_by_alias(settings.model_registry_alias)
    log_evaluation_to_mlflow(
        evaluation, run_id=current.run_id if current else None, settings=settings
    )


async def _run_incremental_chunk_job(
    chunk_start: date,
    chunk_end: date,
    prior_run_id: str | None,
    evaluate_and_promote: bool,
) -> dict[str, Any]:
    """Runs one chunk of `training/incremental.py`'s year-by-year
    incremental training, returning a small JSON-safe summary (not the
    full `IncrementalChunkResult`, which carries a live `DemandLSTM`/
    `WindowedDataset` -- not something a status-polling API response
    should be lugging around).
    """
    from .training.incremental import run_incremental_chunk

    chunk_result = await run_incremental_chunk(
        chunk_start,
        chunk_end,
        prior_run_id=prior_run_id,
        evaluate_and_promote=evaluate_and_promote,
    )
    return {
        "run_id": chunk_result.train_result.run_id,
        "best_val_loss": chunk_result.train_result.best_val_loss,
        "epochs_trained": chunk_result.train_result.epochs_trained,
        "chunk_start": chunk_result.chunk_start,
        "chunk_end": chunk_result.chunk_end,
        "prior_run_id": chunk_result.prior_run_id,
        "registered_version": chunk_result.registered_version,
        "promoted": chunk_result.promoted,
        "promotion_reason": chunk_result.promotion_reason,
    }


@router.post("/train-incremental-chunk")
async def trigger_train_incremental_chunk(
    background_tasks: BackgroundTasks,
    start_date: date = Query(
        ..., description="First day of this chunk (YYYY-MM-DD), inclusive."
    ),
    end_date: date = Query(
        ..., description="Last day of this chunk (YYYY-MM-DD), inclusive."
    ),
    prior_run_id: str | None = Query(
        None,
        description=(
            "Run ID to continue from (restores model weights, Adam's "
            "optimizer state, and the fitted scaler). Omit for the first "
            "chunk in a new incremental sequence."
        ),
    ),
    evaluate_and_promote: bool = Query(
        False,
        description=(
            "Run evaluate -> register -> promote-if-better on this "
            "chunk's result. Only set this for the LAST chunk in a "
            "sequence -- intermediate chunks are checkpoint hand-offs, "
            "not production candidates."
        ),
    ),
) -> dict[str, str]:
    """Trains one date-bounded chunk of `training/incremental.py`'s
    year-by-year incremental training loop -- see that module's
    docstring for the full design (fixed scaler across chunks, Adam
    momentum carried forward via `prior_run_id`'s checkpoint).

    Runs in the background (a chunk's epoch count is the same as a full
    `train_model()` run, so this can take minutes) -- poll
    `GET /forecasting/train-incremental-chunk/{job_id}` with the
    returned `job_id` for the result (`run_id` -- feed this back in as
    the *next* chunk's `prior_run_id`).
    """
    if end_date < start_date:
        raise HTTPException(
            status_code=422, detail="end_date must be on or after start_date"
        )

    job_id = _jobs.start(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        prior_run_id=prior_run_id,
        evaluate_and_promote=evaluate_and_promote,
    )
    background_tasks.add_task(
        _jobs.run,
        job_id,
        _run_incremental_chunk_job,
        start_date,
        end_date,
        prior_run_id,
        evaluate_and_promote,
    )
    log.info(
        "api.train_incremental_chunk_triggered",
        job_id=job_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        prior_run_id=prior_run_id,
    )
    return {
        "status": "started",
        "job_id": job_id,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
    }


@router.get("/train-incremental-chunk/{job_id}")
async def get_train_incremental_chunk_status(job_id: str) -> dict[str, Any]:
    """Poll a `/forecasting/train-incremental-chunk` trigger's outcome.

    `status` is `"running"`, `"completed"`, or `"failed"`; `result`
    (only set once `completed`) is the chunk's summary -- most
    importantly `run_id`, which is what the *next* chunk's
    `prior_run_id` should be.
    """
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail=f"No such job: {job_id!r} (unknown, or the server restarted since it ran)",
        )
    return {
        **job.meta,
        "job_id": job.job_id,
        "status": job.status,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "result": job.result,
        "error": job.error,
    }


@router.post("/train")
async def trigger_train(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Kicks off train -> evaluate -> promote-if-better in the background
    -- a full run can take minutes, so this returns immediately rather
    than holding the request open. Poll `/forecasting/status` for the
    result.
    """
    background_tasks.add_task(_run_training_job)
    log.info("api.train_triggered")
    return {"status": "started"}


@router.post("/evaluate")
async def trigger_evaluate(background_tasks: BackgroundTasks) -> dict[str, str]:
    """Re-scores the current production model against a fresh snapshot,
    in the background.
    """
    background_tasks.add_task(_run_evaluation_job)
    log.info("api.evaluate_triggered")
    return {"status": "started"}


@router.get("/status")
async def model_status() -> dict[str, Any]:
    settings = get_settings()
    registry = ModelRegistry(settings=settings)
    snapshot = get_health_snapshot(registry, alias=settings.model_registry_alias)
    return {
        "model_name": snapshot.model_name,
        "alias": snapshot.alias,
        "has_production_model": snapshot.has_production_model,
        "production_version": snapshot.production_version,
        "last_trained_at": (
            snapshot.last_trained_at.isoformat() if snapshot.last_trained_at else None
        ),
        "last_eval_metrics": snapshot.last_eval_metrics,
    }


__all__ = ["router"]
