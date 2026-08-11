"""Publishes the "warehouse transform completed, incremental training
may run" event once a real `dbt build` (`api/v1/dbt/routes.py`'s
`POST /v1/dbt/build`) succeeds -- ported from data-pipeline's
`pipeline.flows.publish_training_trigger`, minus the Prefect `@task`
wrapper (this service has no Prefect dependency at all; `api/v1/dbt/
routes.py` already runs the build as a plain `asyncio.to_thread` call,
not a flow) -- same payload shape, same reasoning, just invoked directly
from the route instead of a flow step.

`forecast-api`'s `app.service.training_worker.handle_training_trigger`
is the consumer; this module only ever publishes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.rabbitmq import publish_training_trigger_event
from app.db.session import get_session

log = get_logger(__name__)

#: Architectures that get a fine-tune off of every training-trigger
#: event. `"lstm"`/`"tft"` are warm-started incremental fine-tunes of
#: their own weights. `"timesfm_correction"` (added 2026-08-11) is
#: different in kind but the same in spirit: raw TimesFM itself is
#: zero-shot and genuinely has no weights to update, but forecast-api's
#: `service/ml/timesfm_correction.py` fits a small, real Ridge
#: residual-correction layer *on top of* TimesFM's frozen output, and
#: that layer *can* (and should) keep re-fitting as new data lands --
#: excluding it here would leave TimesFM as the one architecture in the
#: platform's "continuously adapts to new data" story that never
#: actually does.
INCREMENTAL_ARCHITECTURES: tuple[str, ...] = ("lstm", "tft", "timesfm_correction")


async def publish_training_trigger(
    regions: list[str],
    window_hours: int,
    *,
    architecture: str = "lstm",
    triggered_by: str = "schedule",
) -> dict:
    """Builds and publishes one training-trigger payload: the dataset
    the build refreshed, the timestamp window `forecast-api`'s
    incremental trainer should query, and a real anomaly-flag count from
    `meta.anomalies` over that same window -- not a placeholder field.

    `architecture` (one of `INCREMENTAL_ARCHITECTURES`) is threaded into
    the payload so `training_worker.handle_training_trigger` dispatches
    to the right incremental trainer and registered model name --
    callers that want every architecture fine-tuned from the same build
    call this once per `INCREMENTAL_ARCHITECTURES` entry, not once
    overall.

    `triggered_by` defaults to `"schedule"` (the automatic post-build
    path, `api/v1/dbt/routes.py`'s `trigger_dbt_build`); a manual
    trigger should pass `"manual"` instead, same convention data-
    pipeline's `trigger_training` used.

    Returns the published payload.
    """
    window_until = datetime.now(UTC)
    window_since = window_until - timedelta(hours=window_hours)
    async with get_session() as db:
        row = (
            await db.execute(
                text("SELECT count(*) FROM meta.anomalies WHERE detected_at >= :since"),
                {"since": window_since},
            )
        ).first()
    anomalies_flagged = int(row[0]) if row is not None else 0

    payload = {
        "event": "warehouse.transform.completed",
        "occurred_at": window_until.isoformat(),
        "dataset": "raw_marts.fct_energy_demand",
        "regions": regions,
        "window_since": window_since.isoformat(),
        "window_until": window_until.isoformat(),
        "anomalies_flagged": anomalies_flagged,
        "architecture": architecture,
        "triggered_by": triggered_by,
    }
    await publish_training_trigger_event(payload)
    log.info(
        "training_trigger.published",
        regions=regions,
        window_since=payload["window_since"],
        anomalies_flagged=anomalies_flagged,
        architecture=architecture,
    )
    return payload


async def publish_training_triggers_for_build(
    *, triggered_by: str = "schedule"
) -> list[dict]:
    """One `publish_training_trigger` call per `INCREMENTAL_ARCHITECTURES`
    entry, using `Settings.model_default_regions`/
    `incremental_train_window_hours` -- what `trigger_dbt_build` calls
    right after a build exits `0`. Failure here is logged, not raised --
    a broken publish shouldn't turn a successful `dbt build` into a
    failed HTTP response; the build already happened and is already
    logged in `meta._dbt_build_log` regardless.
    """
    settings = get_settings()
    published = []
    for architecture in INCREMENTAL_ARCHITECTURES:
        try:
            payload = await publish_training_trigger(
                settings.model_default_regions,
                settings.incremental_train_window_hours,
                architecture=architecture,
                triggered_by=triggered_by,
            )
            published.append(payload)
        except Exception as exc:  # noqa: BLE001 - one bad publish must not fail the build response
            log.error(
                "training_trigger.publish_failed",
                architecture=architecture,
                error=str(exc),
            )
    return published
