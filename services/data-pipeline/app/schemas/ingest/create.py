from __future__ import annotations

from app.schemas.base import AppBaseModel


class IngestRequest(AppBaseModel):
    """Body for `POST /v1/ingest/{source}`.

    `lookback_minutes` is what the 4 time-series sources
    (oe/aemo-nem/aemo-wem/bom) take; `year` is what `holidays` takes
    instead. Both optional — omit either to use the task's own default.
    """

    lookback_minutes: int | None = None
    year: int | None = None
