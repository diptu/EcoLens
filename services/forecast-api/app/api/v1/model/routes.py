"""`GET /v1/model` — currently-served model metadata (`README.md` § API
reference)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.deps import get_app_settings, get_model_registry
from app.schemas.model import ModelInfo
from app.core.config import Settings
from app.service.ml.registry import ModelRegistry

router = APIRouter(prefix="/v1", tags=["model"])


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
