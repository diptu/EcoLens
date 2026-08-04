from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.data_quality import router as data_quality_router
from app.api.v1.datasources import router as datasources_router
from app.api.v1.dbt import router as dbt_router
from app.api.v1.health import router as health_router
from app.api.v1.ingest import router as ingest_router
from app.api.v1.model import router as model_router
from app.api.v1.pipelines import router as pipelines_router

# Each resource router already declares its own full `/v1/...` prefix (see
# each `routes.py`), so this aggregator adds none of its own -- unlike
# IAM's `api_router = APIRouter(prefix="/api/v1")`, doing that here would
# double up the prefix and break the deployed `/v1/...` URL contract
# (docker-compose's healthcheck, the dashboard client, API_SPEC.md).
api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(dbt_router)
api_router.include_router(ingest_router)
api_router.include_router(datasources_router)
api_router.include_router(data_quality_router)
api_router.include_router(pipelines_router)
api_router.include_router(model_router)
