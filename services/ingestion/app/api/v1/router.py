from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.data_quality import router as data_quality_router
from app.api.v1.datasources.routes import router as datasources_router
from app.api.v1.health import router as health_router
from app.api.v1.ingest.routes import router as ingest_router
from app.api.v1.ingestion.routes import router as ingestion_router

# Each resource router declares its own full `/v1/...` prefix -- this
# aggregator adds none of its own (same convention as data-pipeline's
# identical `router.py`).
api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(datasources_router)
api_router.include_router(ingest_router)
api_router.include_router(ingestion_router)
api_router.include_router(data_quality_router)
