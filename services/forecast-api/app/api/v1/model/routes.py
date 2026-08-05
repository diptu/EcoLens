"""`GET /v1/model` — currently-served model metadata (`README.md` § API
reference). `GET /v1/model/versions` — every registered version, any
stage (Model Operations TODO.md Phase 1). `POST /v1/model/versions/
{version}/promote` — real, gated stage transitions (Phase 3).
`DELETE /v1/model/versions/{version}` — real, gated registry-entry
removal (2026-08-05); refuses the current Production version."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from mlflow.exceptions import MlflowException

from app.api.v1.deps import get_app_settings, get_model_registry
from app.core.errors import ApiError
from app.schemas.model import (
    LossCurveOut,
    LossCurvePointOut,
    ModelInfo,
    ModelVersionOut,
    ModelVersionsListResponse,
    PromoteModelRequest,
)
from app.core.config import Settings
from app.service.ml.registry import (
    DeletionRejected,
    ModelRegistry,
    PromotionRejected,
    delete_model_version,
    get_loss_curve,
    list_versions,
    promote_version,
)

router = APIRouter(prefix="/v1", tags=["model"])


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


@router.post("/model/versions/{version}/promote", response_model=ModelVersionOut)
async def promote_model_version(
    version: str,
    body: PromoteModelRequest,
    settings: Settings = Depends(get_app_settings),
) -> ModelVersionOut:
    model_name = body.model_name or settings.mlflow_registry_model_name
    try:
        summary = await promote_version(model_name, version, body.stage)
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
