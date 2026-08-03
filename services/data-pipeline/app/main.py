"""FastAPI application factory for the data-pipeline control plane.

Served by `uvicorn app.main:app` (see TODO.md's ECO-D49 Dockerfile
CMD). `create_app()` exists separately from the module-level `app` so
tests can build a fresh instance per test if they need to.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import __version__
from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.errors import ApiError, api_error_handler
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestIdMiddleware
from app.db.session import dispose, get_engine

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    get_engine()  # eagerly build the connection pool rather than on first request
    logger.info("data_pipeline_api_startup")
    try:
        yield
    finally:
        await dispose()
        logger.info("data_pipeline_api_shutdown")


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="ecoLens data-pipeline",
        version=__version__,
        lifespan=lifespan,
    )

    # CORSMiddleware must be the OUTERMOST middleware (added last — Starlette
    # wraps outside-in in reverse registration order). `RequestIdMiddleware`
    # is a `BaseHTTPMiddleware`, and when an unhandled exception occurs
    # inside the request it's wrapping, `BaseHTTPMiddleware.call_next()`
    # re-raises it directly rather than routing it back through FastAPI's
    # registered `@app.exception_handler(Exception)` — so the resulting
    # error response was, until this fix, built even further out (by
    # Starlette's own `ServerErrorMiddleware`) with no CORS headers at all.
    # A browser `fetch()` against that response reports it as an opaque
    # "Failed to fetch" (no distinguishable status/body), not the real
    # error — confirmed by reproducing this exact failure against
    # `GET /v1/ingestion/public/pipelines` and comparing response headers
    # with `curl -H "Origin: ..."` against a route that doesn't hit this
    # path. Registering CORSMiddleware last guarantees it wraps every
    # response this app ever produces, including ones from exceptions
    # that bypass every other handler.
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # `add_exception_handler(ApiError, api_error_handler)` fails mypy: its
    # `handler` parameter is typed `ExceptionHandler` (a plain, non-generic
    # `Callable[[Request, Exception], ...]`), so a handler whose second
    # param is narrowed to `ApiError` doesn't structurally match even
    # though Starlette only ever calls it with an `ApiError` at runtime
    # (it's keyed by the class passed as the first argument). The
    # decorator form below routes through `FastAPI.exception_handler`,
    # which accepts the same function via an unconstrained `DecoratedCallable`
    # `TypeVar` instead of `ExceptionHandler`, sidestepping the mismatch —
    # same registration, same runtime behavior, no `# type: ignore` needed.
    app.exception_handler(ApiError)(api_error_handler)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.error("unhandled_exception", path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500, content={"detail": "internal server error"}
        )

    app.include_router(api_router)

    return app


app = create_app()
