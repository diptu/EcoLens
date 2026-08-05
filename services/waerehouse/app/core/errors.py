"""Standard error envelope, matching data-pipeline/ingestion's convention:

```json
{"error": {"code": "forbidden", "message": "...", "field": null, "request_id": "..."}}
```

Ported verbatim -- fully generic, no warehouse-specific logic.
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
