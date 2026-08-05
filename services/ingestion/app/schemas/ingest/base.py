from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import AppBaseModel

TriggeredBy = Literal["manual", "schedule", "backfill", "shadow"]

# Must stay in sync with `pipeline.tasks.registry.SOURCES`'s keys --
# hardcoded rather than built dynamically from that dict because a
# `Literal[...]`'s members have to be literal at type-check time (same
# reasoning as `app.api.v1.datasources.routes`'s own `SortField`/`Order`).
# Typing the `{source}` path param as this instead of a bare `str`
# (`app/api/v1/ingest/routes.py`) is what turns it into an actual
# dropdown in the interactive API docs (`/docs`) instead of a free-text
# box a caller has to know the valid values for by reading source code.
IngestSourceKey = Literal["oe", "aemo-nem", "aemo-wem", "bom", "holidays"]

# `holidays` excluded -- it's an annual snapshot, not a per-day time
# series, same reasoning as `pipeline.backfill.BACKFILLABLE_SOURCES`
# (which this is a `Literal` mirror of, for the same "dropdown in /docs"
# reason `IngestSourceKey` exists).
BackfillableSourceKey = Literal["oe", "aemo-nem", "aemo-wem", "bom"]


class IngestRequest(AppBaseModel):
    """Body for `POST /v1/ingest/{source}` — all optional. `lookback_minutes`
    applies to `oe`/`aemo-nem`/`aemo-wem`/`bom`; `year` applies to
    `holidays` only. Passing the wrong one for a given `source` is a
    harmless no-op — `run_source` only forwards the kwargs a source's own
    `run()` actually accepts."""

    lookback_minutes: int | None = Field(default=None, ge=1)
    year: int | None = None
    triggered_by: TriggeredBy = "manual"


class IngestResponse(AppBaseModel):
    """Synchronous result — unlike `POST /v1/data-sources/{id}/run`
    (202, backgrounded), this awaits the real fetch and returns the
    actual outcome: same one-shot-CLI-equivalent shape as `ecolens-
    ingestion ingest <source>`. `rows_staged` is rows written to this
    run's DuckDB file (`services/ingestion/TODO.md` Phase 1's own
    "staged, not yet loaded into Postgres `raw.*`" distinction), not
    rows loaded into the warehouse."""

    source: IngestSourceKey
    rows_staged: int
    triggered_by: str


class IngestBackfillRequest(AppBaseModel):
    """Body for `POST /v1/ingest/{source}/backfill` — `start`/`end` are
    plain calendar dates (inclusive of both ends, matching `pipeline.
    backfill.daterange`'s own semantics), not datetimes; there's no
    `chunk`/`concurrency` here unlike `POST /v1/data-sources/{id}/
    backfill` — execution is always one real day at a time, sequentially,
    same as the CLI's `backfill` command this endpoint mirrors."""

    start: date
    end: date
    lookback_minutes: int = Field(default=1440, ge=1)


class BackfillDayResult(AppBaseModel):
    day: date
    outcome: str


class IngestBackfillResponse(AppBaseModel):
    """Day-by-day result of one backfill run — every `(day, outcome)`
    pair for the requested range. `outcome` is one of `"skipped"`
    (already `success`/`staged` in `meta._ingest_log`), `"success"`, or
    `"failed: <message>"` — see `pipeline.backfill.backfill_day`'s own
    docstring; one failed day never aborts the rest of the range.

    Not returned directly by `POST /v1/ingest/{source}/backfill` itself
    (that's now `202` + `IngestBackfillTriggerResponse`, backgrounded) —
    this is what `GET /v1/ingest/{source}/backfill/status`'s `result`
    field holds once the background run finishes (`service.pipeline.
    backfill_jobs`)."""

    source: BackfillableSourceKey
    start: date
    end: date
    total_days: int
    succeeded: int
    skipped: int
    failed: int
    days: list[BackfillDayResult]


class IngestBackfillTriggerResponse(AppBaseModel):
    """`202` response for `POST /v1/ingest/{source}/backfill` — same
    `backfill_id`/`queued_at`/progress-polling shape `POST /v1/data-
    sources/{id}/backfill`'s `BackfillTriggerResponse` already uses
    (`schemas.datasources.response`), scoped to a plain `registry.
    SOURCES` key (`source`) instead of a catalog id — no `chunk`/
    `concurrency`/`deduplicate` here, same simpler-surface reasoning
    `IngestBackfillRequest` already documents."""

    backfill_id: str
    source: BackfillableSourceKey
    queued_at: datetime
    start: date
    end: date
    total_days: int
    lookback_minutes: int


class IngestBackfillStatusResponse(AppBaseModel):
    """`GET /v1/ingest/{source}/backfill/status` — `running=True` +
    `trigger` while `service.pipeline.backfill_jobs.run_in_background`
    is still going; `running=False` + `result` (the full day-by-day
    summary) once it's finished, for as long as `backfill_jobs` keeps
    the last result cached in Redis; `running=False` with neither once
    that window has passed and nothing new has been triggered since."""

    source: BackfillableSourceKey
    running: bool
    trigger: IngestBackfillTriggerResponse | None = None
    result: IngestBackfillResponse | None = None
