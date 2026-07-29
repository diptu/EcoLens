"""FastAPI app factory for data-pipeline's own internal control API --
mounts the forecasting control surface (`ecolens.forecasting.api`), the
ingestion control surface (`ecolens.ingestion.api`), and the warehouse
pipeline control surface (`ecolens.warehouse.api.runner_router`). Internal
only: `forecast-api` never calls this (see `forecasting/api.py`'s
module docstring); it's for manually/cron-triggering training,
historical backfills, and dbt warehouse runs without shell access to
this repo -- and, as of the `services/dashboard` admin section, for a
browser calling straight from `Settings.api_cors_origins` (the
dashboard's dev origin by default) rather than only curl/scripts.

Run via `make pipeline` (`uvicorn ecolens.api.app:app --reload --port 8001`).
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ecolens.config import get_settings
from ecolens.forecasting.api import router as forecasting_router
from ecolens.ingestion.api import router as ingestion_router
from ecolens.warehouse.api.runner_router import router as warehouse_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="ecoLens Data-Pipeline Control API",
        version="1.0.0",
        description=(
            "Internal control surface for the forecasting pipeline, "
            "historical-ingestion backfills, and the warehouse (dbt) "
            "pipeline. Not a public contract."
        ),
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().api_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(forecasting_router)
    app.include_router(ingestion_router)
    app.include_router(warehouse_router)
    return app


app = create_app()

__all__ = ["create_app", "app"]
