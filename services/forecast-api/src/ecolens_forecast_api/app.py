"""FastAPI app factory + lifespan for forecast-api.

Resilient startup: if the warehouse Postgres is unreachable when the
app boots, the app still comes up but `/health` reports degraded and
`/v1/forecast/*` 503s via `dependencies.require_pool` until a
connection is made. Mirrors data-pipeline's
`ecolens.warehouse.api.app`.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from .cache import Cache
from .db import ConnectionPool
from .forecasting.reload import ModelReloader
from .logging import get_logger
from .routes import router
from .settings import ForecastApiSettings, get_forecast_api_settings

log = get_logger(__name__)


def _build_lifespan(
    settings: ForecastApiSettings,
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    """Bind `settings` into a lifespan context manager for this one app instance."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = settings
        app.state.start_time = time.time()

        pool = ConnectionPool(settings)
        try:
            await pool.connect()
        except Exception as exc:  # noqa: BLE001
            log.error("app.startup.db_unavailable", error=str(exc))
        app.state.pool = pool

        cache = Cache(settings)
        try:
            await cache.connect()
        except Exception as exc:  # noqa: BLE001
            log.warning("app.startup.cache_unavailable", error=str(exc))
        app.state.cache = cache

        # ECO-F04: same resilient-startup pattern as pool/cache above -- an
        # unreachable MLflow server (or no model registered yet) must not
        # block app startup. reload_once() inside start() already degrades
        # internally; the try/except here is just defence in depth against
        # ModelReloader construction itself failing (e.g. a malformed
        # mlflow_tracking_uri).
        reloader = ModelReloader(settings)
        try:
            await reloader.start()
        except Exception as exc:  # noqa: BLE001
            log.warning("app.startup.model_unavailable", error=str(exc))
        app.state.reloader = reloader

        log.info("app.startup", host=settings.api_host, port=settings.api_port)
        yield

        await reloader.stop()
        await pool.disconnect()
        await cache.disconnect()
        log.info("app.shutdown")

    return lifespan


def create_app(settings: ForecastApiSettings | None = None) -> FastAPI:
    """Build the forecast-api FastAPI app.

    `settings` is accepted for tests that want to construct the app
    without going through the cached `get_forecast_api_settings()`
    singleton; production always uses the default (None -> cached).
    """
    resolved_settings = (
        settings if settings is not None else get_forecast_api_settings()
    )
    app = FastAPI(
        title="ecoLens Forecast API",
        version="0.1.0",
        description=(
            "Low-latency demand-forecast serving over the warehouse's "
            "ml_features_demand_v1 mart. Reads only -- never touches MongoDB "
            "or the raw.* Postgres schema."
        ),
        lifespan=_build_lifespan(resolved_settings),
    )
    app.include_router(router)
    return app


__all__ = ["create_app"]
