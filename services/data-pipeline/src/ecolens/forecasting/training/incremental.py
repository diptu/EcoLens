"""Year-by-year (or any other date-chunked) incremental training.

Root motivation: this repo's warehouse Postgres and historical MongoDB
cluster (`MONGO_URI_HISTORICAL`, see `ingestion/api.py`) both run on
free/cheap-tier infrastructure with real storage limits -- backfilling
*all* of AEMO/BoM history in one shot and training against the whole
thing at once isn't always the shape available. The alternative this
module implements: ingest one chunk (e.g. one calendar year) at a time,
train against just that chunk, persist a checkpoint, then move on to
the next chunk -- optionally purging the previous chunk's raw data
first (not yet built, see `plan.md`'s "Incremental Training" section
for the full design, including why purging needs a small overlap
buffer for lookback-window continuity across chunk boundaries).

Two traps this exists specifically to avoid (both concrete, present
gaps this module closes -- see each one's code comment below for
exactly where):

  1. **Feature-scale drift.** Fitting a fresh `FeatureScaler` per chunk
     (2023's mean/std, then 2024's, then 2025's, ...) shifts the LSTM's
     input distribution at every chunk boundary. Fixed by fitting the
     scaler *once*, on the first chunk, and reusing it for every later
     chunk (`build_windowed_dataset`'s `scaler` param).
  2. **Optimizer momentum reset.** Re-instantiating `torch.optim.Adam`
     fresh for each chunk (as `training/online.py`'s `fine_tune()`
     still does, as of this writing) throws away its per-parameter
     momentum/variance buffers, causing erratic loss spikes at the
     start of every new chunk. Fixed by persisting Adam's
     `state_dict()` alongside the model weights (`train_model()`'s
     `initial_optimizer_state`/`TrainResult.optimizer_state`) and
     restoring it before continuing.

Chunk sequencing itself (which run_id is whose parent, when to
evaluate/register/promote vs. just checkpoint-and-move-on) is this
module's job; the actual per-chunk data fetch is `TrainingSetLoader`'s,
and the actual epoch loop is `train_model()`'s -- this module is
orchestration, not a third training-loop implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from mlflow.tracking import MlflowClient

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger

from ..data import TrainingSetLoader
from ..evaluation.evaluate import evaluate_model, log_evaluation_to_mlflow
from ..features import build_windowed_dataset
from ..mlops.promote import promote_if_better
from ..mlops.registry import ModelRegistry
from .train import TrainResult, train_model

log = get_logger(__name__)

# Architecture fields that must stay identical across every chunk in one
# incremental sequence -- a state_dict only loads into a matching-shaped
# model, so changing any of these mid-sequence (e.g. re-tuning hidden_size
# between chunks) would break continuation, not just make it suboptimal.
_ARCHITECTURE_FIELDS = ("model_hidden_size", "model_num_layers", "model_dropout")


@dataclass
class IncrementalChunkResult:
    """One chunk's outcome -- always has `train_result` (the same shape
    a plain `train_model()` call returns); `registered_version`/
    `promoted`/`promotion_reason` are only set when `evaluate_and_promote`
    was requested (see `run_incremental_chunk`'s docstring for why
    intermediate chunks normally skip this).
    """

    train_result: TrainResult
    chunk_start: str
    chunk_end: str
    prior_run_id: str | None
    registered_version: str | None = None
    promoted: bool | None = None
    promotion_reason: str | None = None


def _check_architecture_matches(
    checkpoint_architecture: dict[str, int | float], settings: Settings
) -> None:
    expected = {
        "hidden_size": settings.model_hidden_size,
        "num_layers": settings.model_num_layers,
        "dropout": settings.model_dropout,
    }
    mismatched = {
        key: (checkpoint_architecture.get(key), value)
        for key, value in expected.items()
        if checkpoint_architecture.get(key) != value
    }
    if mismatched:
        raise ValueError(
            "prior_run_id's architecture doesn't match current settings "
            f"(field: (checkpoint_value, current_value)): {mismatched} -- "
            "hidden_size/num_layers/dropout must stay identical across an "
            "incremental sequence's chunks, since a state_dict only loads "
            "into a matching-shaped model"
        )


async def run_incremental_chunk(
    chunk_start: date,
    chunk_end: date,
    *,
    prior_run_id: str | None = None,
    evaluate_and_promote: bool = False,
    settings: Settings | None = None,
) -> IncrementalChunkResult:
    """Trains one chunk `[chunk_start, chunk_end]` (inclusive), either
    starting fresh (`prior_run_id=None` -- the *first* chunk in a new
    sequence, which also fits and owns the canonical scaler every later
    chunk will reuse) or continuing from an earlier chunk's checkpoint
    (`prior_run_id` set -- loads that run's model weights + optimizer
    state + scaler via `ModelRegistry.load_checkpoint`).

    `evaluate_and_promote=True` runs the usual evaluate -> register ->
    promote_if_better tail (see `cli.py`'s `cmd_train`) against this
    chunk's result -- pass this only for the *last* chunk in a sequence
    (or a periodic re-run against the live/current chunk in steady
    state). Intermediate chunks are pure checkpoint hand-offs, not
    production candidates: registering/promoting every chunk would spam
    the registry with versions nobody should ever serve, since a
    mid-sequence checkpoint has only seen part of the intended training
    history.
    """
    settings = settings or get_settings()

    since = datetime(
        chunk_start.year, chunk_start.month, chunk_start.day, tzinfo=timezone.utc
    )
    until = datetime(
        chunk_end.year, chunk_end.month, chunk_end.day, tzinfo=timezone.utc
    ) + timedelta(days=1)
    df = await TrainingSetLoader(settings=settings).fetch(since=since, until=until)

    initial_model_state = None
    initial_optimizer_state = None
    scaler = None
    if prior_run_id is not None:
        registry = ModelRegistry(settings=settings)
        checkpoint = registry.load_checkpoint(prior_run_id)
        _check_architecture_matches(checkpoint.architecture, settings)
        initial_model_state = checkpoint.model_state
        initial_optimizer_state = checkpoint.optimizer_state
        scaler = checkpoint.scaler

    dataset = build_windowed_dataset(
        df,
        lookback=settings.model_lookback,
        horizon=settings.model_horizon,
        scaler=scaler,
    )

    result = train_model(
        dataset,
        settings=settings,
        initial_model_state=initial_model_state,
        initial_optimizer_state=initial_optimizer_state,
    )

    # Tags the run with its place in the chunk sequence so the whole
    # thing is browsable as a lineage chain in the MLflow UI, not a pile
    # of disconnected/anonymous runs -- set post-hoc (not inside
    # train_model()'s own mlflow.start_run() block) so train_model()'s
    # signature doesn't need an incremental-specific "extra tags" param.
    client = MlflowClient(tracking_uri=settings.mlflow_tracking_uri)
    client.set_tag(result.run_id, "chunk_start", chunk_start.isoformat())
    client.set_tag(result.run_id, "chunk_end", chunk_end.isoformat())
    if prior_run_id is not None:
        client.set_tag(result.run_id, "parent_run_id", prior_run_id)

    chunk_result = IncrementalChunkResult(
        train_result=result,
        chunk_start=chunk_start.isoformat(),
        chunk_end=chunk_end.isoformat(),
        prior_run_id=prior_run_id,
    )

    if evaluate_and_promote:
        evaluation = evaluate_model(
            result.model, dataset, alpha=settings.conformal_alpha
        )
        log_evaluation_to_mlflow(evaluation, run_id=result.run_id, settings=settings)
        registry = ModelRegistry(settings=settings)
        registered = registry.register(result.run_id)
        decision = promote_if_better(
            registry, registered, evaluation, alias=settings.model_registry_alias
        )
        chunk_result.registered_version = registered.version
        chunk_result.promoted = decision.promote
        chunk_result.promotion_reason = decision.reason

    log.info(
        "incremental.chunk_complete",
        run_id=result.run_id,
        chunk_start=chunk_result.chunk_start,
        chunk_end=chunk_result.chunk_end,
        prior_run_id=prior_run_id,
        best_val_loss=round(result.best_val_loss, 4),
        evaluated=evaluate_and_promote,
        promoted=chunk_result.promoted,
    )
    return chunk_result


__all__ = ["IncrementalChunkResult", "run_incremental_chunk"]
