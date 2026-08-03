"""Training-trigger consumer entrypoint (`ecolens-pipeline train-worker`,
the `train-worker` docker-compose service) — `TODO.md`'s "Event-Driven
Pipeline Trigger for Online/Incremental Model Training", item 3's
"resilient message consumer... in the forecasting service". Per
`README.md`'s own service-boundary rule ("`forecast-api` never trains")
this lives in `data-pipeline`, the service that already owns `ml/train.py`,
MLflow, and the warehouse connection — not in `forecast-api`.

Structurally identical to `app.service.worker` (the warehouse-sync consumer):
a long-running RabbitMQ consume loop wired to a per-message handler,
meant to run as its own OS process (own container, own docker-compose
service), never inside `forecast-api`'s request/response cycle. This is
what satisfies `TODO.md`'s "Non-Blocking Training Architecture" item 5's
core requirement ("never run a training loop synchronously inside
forecast-api's request/response cycle") in practice: training here is not
reachable from any HTTP handler in either service at all, by construction
— the same guarantee `app.service.worker`'s warehouse-sync consumer already
gives the ingestion path, not a new mechanism invented for this feature.

See `ml.incremental.train_and_register_incremental` for the actual
warm-started fine-tune, and `mq.rabbitmq_client.
consume_training_trigger_events` for the consume loop / DLX behavior on a
failed handler call.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.config import get_settings
from app.service.ml.incremental import train_and_register_incremental
from app.db.rabbitmq import close_rabbitmq, consume_training_trigger_events
from app.core.logging import configure_logging, get_logger

log = get_logger(__name__)


async def handle_training_trigger(payload: dict[str, Any]) -> None:
    """Handle one `publish_training_trigger_event` message
    (`pipeline.flows.publish_training_trigger`'s payload shape): resolve
    the data window and regions from the event, run the incremental
    fine-tune, and let any failure (no warm-startable version yet, empty
    window, a bad/malformed payload) propagate — `consume_training_
    trigger_events`'s `message.process()` nacks on exception, which,
    because the queue's `x-dead-letter-exchange` is set, dead-letters the
    message into `rabbitmq_training_trigger_dlq` rather than silently
    dropping it or retrying forever.
    """
    settings = get_settings()
    regions = payload.get("regions") or settings.model_default_regions
    window_since = payload.get("window_since")
    since = (
        pd.Timestamp(window_since)
        if window_since
        else pd.Timestamp.now(tz="UTC")
        - pd.Timedelta(hours=settings.incremental_train_window_hours)
    )
    model_name = settings.mlflow_registry_model_name

    result = await train_and_register_incremental(model_name, regions, since)
    log.info(
        "training_worker.incremental_trained",
        model_name=model_name,
        run_id=result.run_id,
        model_version=result.model_version,
        regions=regions,
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
