"""ECO-118 (part 2): the internal control surface for the forecasting
pipeline -- trigger-train, trigger-evaluate, model-status. A plain
`APIRouter` (same shape as `ingestion.api`'s own router), meant to be
mounted on data-pipeline's own control API (`ecolens.api.app`), not a
public contract -- `forecast-api` never calls this, it only ever reads
the MLflow registry (`strategy.md` §2).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks

from ecolens.config import get_settings
from ecolens.shared.observability.logging import get_logger

from .data import TrainingSetLoader
from .evaluation.evaluate import evaluate_model, log_evaluation_to_mlflow
from .features import build_windowed_dataset
from .mlops.health import get_health_snapshot
from .mlops.promote import promote_if_better
from .mlops.registry import ModelRegistry

log = get_logger(__name__)

router = APIRouter(prefix="/forecasting", tags=["forecasting"])


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
