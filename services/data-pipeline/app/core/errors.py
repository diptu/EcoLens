"""Standard error envelope (API_SPECEFICATIONS.md § Conventions).

```json
{"error": {"code": "forbidden", "message": "...", "field": null, "request_id": "..."}}
```

Only the role-gated endpoints that were built against that spec (currently
`api/security.py` and `api/routers/datasources.py`) raise `ApiError`. The
pre-existing routers (ingest, dbt, health) predate the JWT/error-envelope
requirement and still return FastAPI's default `{"detail": ...}` shape via
`app.py`'s catch-all handler — retrofitting them is a separate change, not
bundled into this one.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.middleware import REQUEST_ID_HEADER


class ApiError(Exception):
    """Raise to produce the spec's error envelope with the given status/code."""

    def __init__(
        self, status_code: int, code: str, message: str, field: str | None = None
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.field = field
        super().__init__(message)


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None) or request.headers.get(
        REQUEST_ID_HEADER, ""
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "field": exc.field,
                "request_id": request_id,
            }
        },
    )
