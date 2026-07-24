"""FastAPI app factory + lifespan for the warehouse API.

Resilient startup: if PostgreSQL is unreachable when the app boots,
the app still comes up but `/health` reports degraded and every data
route 503s via `dependencies.require_pool` until a connection is made.
This lets the dashboard show a "data unavailable" banner instead of
the process crash-looping.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from fastapi import FastAPI

from ecolens.shared.observability.logging import get_logger

from .cache import Cache
from .db import ConnectionPool
from .routes import router
from .settings import WarehouseApiSettings, get_warehouse_api_settings

log = get_logger(__name__)


def _build_lifespan(
    settings: WarehouseApiSettings,
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

        log.info("app.startup", host=settings.api_host, port=settings.api_port)
        yield

        await pool.disconnect()
        await cache.disconnect()
        log.info("app.shutdown")

    return lifespan


def create_app(settings: WarehouseApiSettings | None = None) -> FastAPI:
    """Build the warehouse API FastAPI app.

    `settings` is accepted for tests that want to construct the app
    without going through the cached `get_warehouse_api_settings()`
    singleton; production always uses the default (None -> cached).
    """
    resolved_settings = (
        settings if settings is not None else get_warehouse_api_settings()
    )
    app = FastAPI(
        title="ecoLens Warehouse API",
        version="1.0.0",
        description=(
            "Read-only API over the PostgreSQL data warehouse produced by dbt. "
            "Powers the dashboard and forecast-api services. Never queries MongoDB."
        ),
        lifespan=_build_lifespan(resolved_settings),
    )
    app.include_router(router)
    return app


__all__ = ["create_app"]
