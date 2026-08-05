"""Request-ID propagation. Ported verbatim from `data-pipeline`'s
identical module (`services/ingestion/TODO.md` Phase 1) -- fully
generic, no ingestion-specific logic. See that module's own docstring
for the full "why" (a real `BaseHTTPMiddleware` exception-handling gap
this works around).
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import bind_request_id, clear_context, get_logger

REQUEST_ID_HEADER = "X-Request-ID"

logger = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Deferred import: `app.core.errors` imports `REQUEST_ID_HEADER`
        # from this module at load time, so importing it back at module
        # level here would be circular.
        from app.core.errors import ApiError, api_error_handler

        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        bind_request_id(request_id)
        try:
            try:
                response = await call_next(request)
            except ApiError as exc:
                response = await api_error_handler(request, exc)
            except Exception as exc:  # noqa: BLE001 - last-resort catch, see module docstring
                logger.error(
                    "unhandled_exception", path=request.url.path, error=str(exc)
                )
                response = JSONResponse(
                    status_code=500, content={"detail": "internal server error"}
                )
        finally:
            clear_context()
        response.headers[REQUEST_ID_HEADER] = request_id
        return response
