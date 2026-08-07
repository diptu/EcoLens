"""`GET /v1/ingestion/public/pipelines`, `GET /v1/ingestion/public/runs` —
this service's own equivalent of `services/data-pipeline`'s identically-
named routes, which is what `services/dashboard`'s `lib/ingestion.ts`
currently calls instead of anything here (`services/ingestion/TODO.md`'s
"Frontend integration" section, 2026-08-07: a frontend cutover to this
service needs *some* response-shape-compatible endpoint to switch to,
which didn't exist until now).

Deliberately not a byte-for-byte clone of data-pipeline's shape —
`data-pipeline`'s `PipelineOut` carries fields real here that don't
apply (`stage`, `depends_on`, pause/resume `status`: this service has no
dbt pipeline, no cross-pipeline dependency graph, and no pause/resume
switch — every source just always runs). Fields kept are the ones this
service can back honestly; fields data-pipeline has that this service
can't back are simply not on these models rather than faked with a
placeholder value. `id`/`source_id` reuse this service's own existing
`ds-*` catalog ids (`app.models.datasources.CATALOG`, already what
`GET /v1/data-sources/{id}` uses) — not a new id scheme.
"""

from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class PublicPipelineSchedule(AppBaseModel):
    cron: str
    timezone: str
    enabled: bool


class PublicPipelineOut(AppBaseModel):
    """One `app.models.datasources.CATALOG` entry + its real 24h stats
    from `meta._ingest_log`.

    `schedule.cron` is deliberately **not** `CATALOG[].cron` (each
    source's own intended cadence — `oe` every 5 min, etc.) — it's the
    real cadence `app.celery_app`'s Beat schedule currently dispatches
    at (`*/30 * * * *`, unified across all 5 sources since 2026-08-05).
    Reporting the catalog's aspirational per-source cron here would
    repeat the exact doc-says-X-reality-is-Y problem `TODO.md`'s Ground
    Truth section already had to call out once. `enabled` is always
    `True` — this service has no pause/resume mechanism at all (unlike
    data-pipeline's `meta.pipelines`), so there's no real "disabled"
    state to report; not a fabricated always-on placeholder, a
    genuinely accurate one.
    """

    id: str
    name: str
    source_id: str
    schedule: PublicPipelineSchedule
    last_run_at: datetime | None = None
    next_run_at: datetime | None = None
    run_count_24h: int
    success_rate_24h: float | None = None
    p95_duration_ms_24h: int | None = None


class PublicPipelinesMeta(AppBaseModel):
    total: int
    as_of: datetime


class PublicPipelinesListResponse(AppBaseModel):
    meta: PublicPipelinesMeta
    data: list[PublicPipelineOut]


class PublicRunOut(AppBaseModel):
    """One `meta._ingest_log` row — the unauthenticated projection: no
    `error_message` (raw exception text) or `hostname` (internal infra
    detail), same two fields data-pipeline's own `PublicRunOut` drops
    and for the same reason (see that schema's docstring). `pipeline_id`
    and `source_id` are always equal here (`ds-*` catalog id) — this
    service has no separate pipeline/source id namespace to distinguish
    them the way data-pipeline's dbt-build pipeline (`source_id: null`)
    needs.
    """

    id: str
    pipeline_id: str
    source_id: str
    status: str
    trigger: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    records_fetched: int | None = None
    records_inserted: int | None = None
    duplicates_skipped: int | None = None
    anomalies_flagged: int | None = None


class PublicRunsMeta(AppBaseModel):
    total: int
    filtered: int


class PublicRunsListResponse(AppBaseModel):
    meta: PublicRunsMeta
    data: list[PublicRunOut]
    next_cursor: str | None = None
    has_more: bool
