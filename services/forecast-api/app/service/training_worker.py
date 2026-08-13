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

from app.core.config import Settings, get_settings
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
from app.service.ml.train import train_and_register
from app.service.ml.train_tft import TFT_MODEL_NAME, train_and_register_tft
from app.service.mlops.registry import get_version_in_stage
from app.service.model.actions import log_training_finish, log_training_start

log = get_logger(__name__)


def _resolve_max_acceptable_mape(model_name: str, settings: Settings) -> float | None:
    """Real relative-to-Production ceiling for `run_live_evaluation_
    gate`'s `max_acceptable_mape` -- see `Settings.live_eval_gate_max_
    regression_pct`'s own docstring for the real bug this closes (that
    parameter being silently left `None` made the "never force-
    skippable" live-eval gate unable to fail on accuracy at all).

    Real bug, confirmed live 2026-08-12 against an actual promotion
    attempt: this used to fall back to Production's logged `test_mape`
    (a single, training-time split) when its `eval_gate_mape` tag
    (real walk-forward, out-of-sample) was absent -- v7 (Production)
    predates the live-eval-gate tagging, so every candidate's real
    `eval_gate_mape` was compared against v7's `test_mape` of 8.19,
    with only this setting's 20% tolerance. `test_mape` and walk-
    forward MAPE are not the same metric and don't share a scale --
    this whole module's own history is full of walk-forward running
    higher than the single-split number it's checked against (see
    `Settings.live_eval_gate_max_regression_pct`'s own docstring: v7's
    real walk-forward MAPE is *worse* than naive in 5/6 regions despite
    a fine `test_mape`). Concretely: v16's real `eval_gate_mape`
    (11.01) is roughly in line with v7's *own* real walk-forward MAPE
    computed the same way (~11.24 on the same data) -- a genuine wash,
    not a regression -- yet got rejected against `8.19 * 1.2 = 9.83`,
    an apples-to-oranges threshold built from the easier metric.

    Only a real walk-forward baseline is comparable to the candidate's
    own real walk-forward `eval_gate_mape`, so the `test_mape` fallback
    is gone -- `None` (no ceiling) whenever Production has no real
    `eval_gate_mape` tag yet, same "absent signal doesn't block"
    convention `ml.registry.promote_version`'s own two gates already
    follow, not a new invention. (The `test_mape`-vs-`test_mape`
    comparison `promote_version` does separately is still a fair,
    like-for-like check on its own -- this function just stops
    manufacturing a second, mismatched one.)
    """
    production = get_version_in_stage(model_name, "Production")
    if production is None or production.run_id is None:
        return None

    tag_value = production.tags.get("eval_gate_mape") if production.tags else None
    if not tag_value:
        return None
    try:
        baseline_mape = float(tag_value)
    except ValueError:
        return None

    return baseline_mape * (1 + settings.live_eval_gate_max_regression_pct / 100)


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

    `max_acceptable_mape` (2026-08-11, real fix -- see `Settings.
    live_eval_gate_max_regression_pct`'s own docstring) is now resolved
    from the current Production version's own real accuracy via
    `_resolve_max_acceptable_mape`, not left `None` -- previously this
    call site never set it at all, which made `passed` reduce to "did
    evaluation run against any real data", not "is the real accuracy
    acceptable".
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
        max_acceptable_mape = _resolve_max_acceptable_mape(model_name, get_settings())
        gate_result = await run_live_evaluation_gate(
            forecaster,
            model_name,
            version,
            regions,
            horizon,
            max_acceptable_mape=max_acceptable_mape,
        )
        log.info(
            "training_worker.live_eval_gate",
            model_name=model_name,
            version=version,
            passed=gate_result.passed,
            overall_mape=gate_result.overall_mape,
            max_acceptable_mape=max_acceptable_mape,
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

    `payload["full_retrain"]` (`False` if absent -- every event
    published before this field existed, including every automatic
    post-dbt-build event `services/waerehouse` still publishes today,
    correctly keeps behaving as an incremental fine-tune): `True`
    dispatches to the real from-scratch trainer instead --
    `ml.train.train_and_register`/`ml.train_tft.train_and_register_tft`,
    the same functions `ecolens-forecast train`/`train-tft` already call
    from the CLI, now reachable from a manual `POST /v1/model/train`
    trigger too (2026-08-11 -- previously the dashboard's "Train a new
    version" tab had no trigger endpoint at all). Neither function sets
    a `training_type` tag, same as any other full retrain -- what
    `divergence.find_last_full_retrain_run_id` already keys off of to
    find a real anchor to compare incremental drift against, so a full
    retrain triggered this way is indistinguishable from one triggered
    by the CLI, as it honestly should be. No real distinction for
    `timesfm_correction` here either (see this field's own note on
    `TrainRequest.full_retrain`) -- it always dispatches to
    `train_and_register_correction` regardless of this flag.

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
    full_retrain = bool(payload.get("full_retrain", False))
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
        if full_retrain and architecture == "tft":
            result = await train_and_register_tft(model_name, regions, since=since)
        elif full_retrain and architecture != "timesfm_correction":
            result = await train_and_register(model_name, regions, since=since)
        elif architecture == "tft":
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
        "training_worker.trained",
        model_name=model_name,
        run_id=result.run_id,
        model_version=result.model_version,
        regions=regions,
        architecture=architecture,
        full_retrain=full_retrain,
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
