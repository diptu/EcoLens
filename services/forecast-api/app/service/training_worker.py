"""Training-trigger consumer entrypoint (`ecolens-forecast train-worker`,
the `train-worker` docker-compose service) -- ported from data-pipeline's
identical module as part of the training-code migration (`README.md`'s
old "forecast-api never trains" service-boundary rule is retired; this
service owns `ml/train.py`, MLflow, and the warehouse connection now).

Structurally identical to `services/waerehouse`'s `consumers.
landed_events` consumer: a long-running RabbitMQ consume loop wired to a
per-message handler, meant to run as its own OS process (own container,
own docker-compose service), never inside this service's own FastAPI
request/response cycle -- training here is not reachable from any HTTP
handler at all, by construction, satisfying the same "never run a
training loop synchronously inside a request/response cycle" invariant
data-pipeline's original module documents.

Events arrive from two publishers: `services/waerehouse`'s
`dbt.training_trigger.publish_training_trigger` (automatic, right after
a successful `dbt build`) and this service's own
`app.service.model.actions.trigger_training` (manual,
`POST /v1/model/train`) -- both publish the same payload shape to the
same queue; this consumer doesn't care which one fired.

See `ml.incremental.train_and_register_incremental` for the actual
warm-started fine-tune, and `db.rabbitmq.consume_training_trigger_events`
for the consume loop / DLX behavior on a failed handler call.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger
from app.db.rabbitmq import close_rabbitmq, consume_training_trigger_events
from app.service.ml.evaluate import (
    Forecaster,
    load_registered_model,
    load_registered_tft_model,
    run_live_evaluation_gate,
)
from app.service.ml.incremental import train_and_register_incremental
from app.service.ml.incremental_tft import train_and_register_tft_incremental
from app.service.ml.timesfm_correction import (
    TIMESFM_CORRECTION_MODEL_NAME,
    load_registered_correction_model,
    train_and_register_correction,
)
from app.service.ml.train_tft import TFT_MODEL_NAME
from app.service.model.actions import log_training_finish, log_training_start

log = get_logger(__name__)


async def _run_live_evaluation_gate(
    architecture: str,
    model_name: str,
    version: str,
    regions: list[str],
) -> None:
    """Runs right after a fresh incremental version registers, against
    the most recent real warehouse data -- distinct from
    `mlops.registry.promote_version`'s existing gate (training-time
    `test_mape` only). Failure here is logged, not raised -- a broken
    gate check shouldn't fail the training run itself (the version is
    already registered, correctly, in the `None` stage; it just won't
    have an `eval_gate_passed` tag for `promote_version` to consult yet,
    which is a real but non-fatal degradation, not silently pretending
    the gate ran when it didn't).
    """
    try:
        forecaster: Forecaster
        horizon: int
        if architecture == "tft":
            tft_forecaster = load_registered_tft_model(model_name, version)
            forecaster, horizon = tft_forecaster, tft_forecaster.model.horizon
        elif architecture == "timesfm_correction":
            correction_forecaster = load_registered_correction_model(model_name, version)
            forecaster, horizon = correction_forecaster, correction_forecaster.horizon
        else:
            lstm_forecaster = load_registered_model(model_name, version)
            forecaster, horizon = lstm_forecaster, lstm_forecaster.model.horizon
        gate_result = await run_live_evaluation_gate(
            forecaster, model_name, version, regions, horizon
        )
        log.info(
            "training_worker.live_eval_gate",
            model_name=model_name,
            version=version,
            passed=gate_result.passed,
            overall_mape=gate_result.overall_mape,
        )
    except Exception as exc:
        log.error(
            "training_worker.live_eval_gate_failed",
            model_name=model_name,
            version=version,
            error=str(exc),
        )


async def handle_training_trigger(payload: dict[str, Any]) -> None:
    """Handle one training-trigger message (`services/waerehouse`'s
    `dbt.training_trigger.publish_training_trigger`'s payload shape):
    resolve the data window, regions, and target architecture from the
    event, run the incremental fine-tune, and let any failure (no
    warm-startable version yet, empty window, a bad/malformed payload)
    propagate -- `consume_training_trigger_events`'s `message.process()`
    nacks on exception, which, because the queue's
    `x-dead-letter-exchange` is set, dead-letters the message into
    `rabbitmq_training_trigger_dlq` rather than silently dropping it or
    retrying forever.

    `payload["architecture"]` (`"lstm"`, the default if absent -- older
    events published before this ever set it -- `"tft"`, or
    `"timesfm_correction"`) dispatches to `ml.incremental`/
    `ml.incremental_tft`/`ml.timesfm_correction` respectively; the
    publisher calls this once per architecture so all three get a
    fine-tune from the same real dbt-build-completion signal.
    `timesfm_correction` retrains the Ridge residual-correction layer on
    top of frozen zero-shot TimesFM (`service/ml/timesfm_correction.py`'s
    own docstring) -- TimesFM's own weights never move, only that
    layer's, which is what makes "continuously adapts" honestly true for
    TimesFM's contribution the same way it already is for LSTM/TFT.

    Logs a `meta._training_log` row for the full attempt regardless of
    outcome (`running` at start, `success`/`failed` at the end) -- the
    real "is a training run in flight right now" signal
    `GET /v1/model/training-runs` reads. After a successful
    registration, also runs the live evaluation gate against fresh data
    (failure there is logged, not fatal to this training run -- see
    `_run_live_evaluation_gate`'s own docstring).
    """
    settings = get_settings()
    regions = payload.get("regions") or settings.model_default_regions
    window_since = payload.get("window_since")
    window_until = payload.get("window_until")
    since = (
        pd.Timestamp(window_since)
        if window_since
        else pd.Timestamp.now(tz="UTC")
        - pd.Timedelta(hours=settings.incremental_train_window_hours)
    )
    until = pd.Timestamp(window_until) if window_until else pd.Timestamp.now(tz="UTC")
    architecture = payload.get("architecture") or "lstm"
    if architecture == "tft":
        model_name = TFT_MODEL_NAME
    elif architecture == "timesfm_correction":
        model_name = TIMESFM_CORRECTION_MODEL_NAME
    else:
        model_name = settings.mlflow_registry_model_name
    triggered_by = payload.get("triggered_by") or "schedule"

    log_id = await log_training_start(
        model_name,
        triggered_by,
        list(regions),
        since.to_pydatetime(),
        until.to_pydatetime(),
    )
    try:
        if architecture == "tft":
            result = await train_and_register_tft_incremental(
                model_name, regions, since
            )
        elif architecture == "timesfm_correction":
            result = await train_and_register_correction(
                model_name, regions, since=since
            )
        else:
            result = await train_and_register_incremental(model_name, regions, since)
    except Exception as exc:
        await log_training_finish(log_id, status="failed", error_message=str(exc))
        raise

    await log_training_finish(
        log_id,
        status="success",
        run_id=result.run_id,
        model_version=result.model_version,
    )
    log.info(
        "training_worker.incremental_trained",
        model_name=model_name,
        run_id=result.run_id,
        model_version=result.model_version,
        regions=regions,
        architecture=architecture,
    )

    if result.model_version:
        await _run_live_evaluation_gate(
            architecture, model_name, result.model_version, list(regions)
        )


async def run() -> None:
    """Run forever, running an incremental training pass as each
    training-trigger event arrives. Exits (and closes the connection) on
    cancellation/interrupt."""
    configure_logging()
    log.info("training_worker.consumer_starting")
    try:
        await consume_training_trigger_events(handle_training_trigger)
    finally:
        await close_rabbitmq()
        log.info("training_worker.consumer_stopped")
