"""`GET /v1/model` — currently-served model metadata (`README.md` § API
reference). `GET /v1/model/versions` — every registered version, any
stage (Model Operations TODO.md Phase 1). `POST /v1/model/versions/
{version}/promote` — real, gated stage transitions (Phase 3)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from mlflow.exceptions import MlflowException

from app.api.v1.deps import get_app_settings, get_model_registry
from app.core.errors import ApiError
from app.schemas.model import (
    ModelInfo,
    ModelVersionOut,
    ModelVersionsListResponse,
    PromoteModelRequest,
)
from app.core.config import Settings
from app.service.ml.registry import (
    ModelRegistry,
    PromotionRejected,
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
    settings: Settings = Depends(get_app_settings),
) -> ModelVersionsListResponse:
    model_name = settings.mlflow_registry_model_name
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


@router.post("/model/versions/{version}/promote", response_model=ModelVersionOut)
async def promote_model_version(
    version: str,
    body: PromoteModelRequest,
    settings: Settings = Depends(get_app_settings),
) -> ModelVersionOut:
    model_name = settings.mlflow_registry_model_name
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
