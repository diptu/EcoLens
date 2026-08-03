from __future__ import annotations

from app.schemas.base import AppBaseModel


class IngestTriggerResponse(AppBaseModel):
    """Response for `POST /v1/ingest/{source}`.

    The endpoint runs the fetch inline and waits for it to finish (same
    convention as `POST /v1/dbt/{subcommand}`), so `status` reflects the
    actual outcome by response time. As of `overview.md` §2's DuckDB ->
    RabbitMQ -> Postgres design, "finish" only means *staged* — the
    Postgres `raw.*` load happens asynchronously once `pipeline.
    warehouse_sync`'s consumer processes the event, so a 200 here means
    `status="staged"` (or `"success"` for a no-op empty fetch), not that
    the rows are in the warehouse yet. `rows_staged` is that count, not
    a Postgres row count. Poll `GET /v1/ingest/runs?source=...` — its
    `status`/`rows_loaded` reflect the real, eventually-consistent
    outcome once the consumer catches up.

    `run_id` is `None` for now: `_common.standard_run`'s wrapper generates
    one internally (written to `meta._ingest_log`) but doesn't return it
    to the caller. Threading the real run_id back through
    `registry.run_source`'s return value is a deliberately separate
    follow-up, not bundled into this ticket.
    """

    run_id: str | None = None
    source: str
    status: str
    rows_staged: int | None = None
