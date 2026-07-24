# Incremental (chunked) PyTorch training — design + implementation

> **Status: the core mechanism is implemented and tested** (data-range
> fetch, fixed-scaler reuse, optimizer-state checkpointing, chunk
> orchestration, one API endpoint per chunk). **Not yet implemented**:
> automatic multi-chunk sequencing, DB-storage purging between chunks,
> and CLI wiring — see "What's not built yet" at the bottom.

## The problem

Train a demand-forecasting LSTM across a rolling window of historical
data (e.g. 2023 → 2024 → 2025 → the live stream) without needing to
hold every year of raw data in the warehouse/historical Mongo cluster
at once — both run on free/cheap-tier infrastructure (Neon Postgres,
MongoDB Atlas) with real storage limits. The shape:

```
[ 2023 chunk ] → Train → Save weights + optimizer state
                              │
[ Load 2024 chunk ] ←─────────┘
        │
        └──→ Load weights + state → Train → Save updated checkpoint
                                                  │
[ Repeat for 2025, 2026, live stream ] ←──────────┘
```

## Two concrete traps — both were real, present gaps in this codebase

Not hypothetical: both are documented, verified gaps I found in the
existing code before writing anything new.

**1. Feature-scale drift.** `features.py`'s `build_windowed_dataset()`
always fit a brand-new `FeatureScaler` from whatever `df` it was
handed (mean/std of that call's own train split). Fitting separately
per chunk — 2023's mean/std, then 2024's, then 2025's — shifts the
LSTM's input distribution at every chunk boundary, confusing a model
whose weights were trained against a *different* normalization.

**2. Optimizer momentum reset.** `training/online.py`'s `fine_tune()` —
the one place this repo already does "continue training an existing
model" — creates a brand-new `torch.optim.Adam(...)` on every call and
never restores a prior run's momentum/variance buffers. This is
*exactly* the trap: every online-fine-tune cycle (and any naive
year-chunk loop built the same way) throws Adam's state away and
restarts from zero, causing the erratic loss spikes at each new
data batch this whole mechanism exists to avoid.

## Design

### 1. Fixed scaler across chunks (`features.py`)

`build_windowed_dataset(df, *, lookback, horizon, scaler=None, ...)` —
new optional `scaler` param. `None` (default, unchanged behavior) fits
fresh from `df`'s own train split, exactly as before. Given a
`FeatureScaler`, it's used verbatim, no fit — the first chunk in a
sequence fits the canonical scaler; every later chunk reuses it.

### 2. Optimizer-state checkpointing (`training/train.py`, `mlops/registry.py`)

- `train_model(..., initial_model_state=None, initial_optimizer_state=None)`
  — both optional. Given, they seed the freshly-constructed
  `DemandLSTM`/`Adam` instead of random-init/zero-momentum.
- `TrainResult` gained `optimizer_state: dict | None` — Adam's
  `state_dict()`, snapshotted **at the same epoch `best_state` is
  snapshotted**, not just the final epoch's. This matters: early
  stopping can pick an earlier epoch as "best," and Adam's state from
  a later epoch would reflect gradients computed against weights the
  checkpoint no longer has — snapshotting them together keeps the
  returned checkpoint internally consistent.
- `log_model_artifacts(model, *, optimizer_state=None)` — logs a
  fourth MLflow artifact (`optimizer_state_dict`) when given. Omitted
  by default, so every run this repo has ever logged stays loadable
  exactly as before.
- `ModelRegistry.load_checkpoint(run_id) -> Checkpoint` (new) — reads
  back `model_state`, `architecture`, `optimizer_state` (`None` if that
  run never logged one), and `scaler` for a specific run_id. Keyed by
  run_id, not alias — intermediate chunks are never registered/
  promoted (see below), so there's no alias pointing at them.

### 3. Date-scoped data fetch (`data.py`)

`TrainingSetLoader.fetch(regions=None, *, since=None, until=None)` —
both new, optional, composable with `regions`. `since`/`until` bound
the SQL query to `[since, until)`. This is what lets a chunk be "just
2023," not "everything in the warehouse."

### 4. Chunk orchestration (`training/incremental.py`, new module)

`run_incremental_chunk(chunk_start, chunk_end, *, prior_run_id=None, evaluate_and_promote=False, settings=None) -> IncrementalChunkResult`:

1. Fetch `[chunk_start, chunk_end]` via `TrainingSetLoader.fetch(since=, until=)`.
2. If `prior_run_id`: load its checkpoint, verify hidden_size/
   num_layers/dropout match `settings` exactly (raises `ValueError`
   otherwise — a state_dict only loads into a matching-shaped model),
   reuse its scaler, seed `train_model()` with its weights+optimizer
   state.
3. If no `prior_run_id` (first chunk): `build_windowed_dataset()` fits
   a fresh scaler; `train_model()` starts from random init — identical
   to today's plain `train_model()` call.
4. Tags the resulting MLflow run with `chunk_start`/`chunk_end`/
   `parent_run_id` (post-hoc, via `MlflowClient.set_tag`) so the whole
   sequence is browsable as a lineage chain in the MLflow UI.
5. `evaluate_and_promote=True` runs the usual evaluate → register →
   promote_if_better tail (same as `cmd_train`) against this chunk.
   **Deliberately not the default**: intermediate chunks are pure
   checkpoint hand-offs, not production candidates — registering every
   chunk would spam the registry with versions nobody should serve,
   since a mid-sequence checkpoint has only seen part of the intended
   training history. Pass this only for the *last* chunk in a sequence
   (or a periodic re-run against the live/current chunk in steady
   state).

### 5. API endpoint (`forecasting/api.py`)

`POST /forecasting/train-incremental-chunk?start_date=...&end_date=...[&prior_run_id=...][&evaluate_and_promote=true]`

Fire-and-forget (a chunk's epoch count is the same as a full
`train_model()` run — this can take minutes), returns
`{"status": "started", "job_id": ...}` immediately. Poll
`GET /forecasting/train-incremental-chunk/{job_id}` for the result —
`status` (`running`/`completed`/`failed`), and once completed,
`result.run_id` (feed this back in as the *next* chunk's
`prior_run_id`).

The job-tracking mechanism (`JobStatus`/`JobTracker`) was extracted to
`ecolens/shared/job_tracker.py` — this is the second router needing
"trigger returns a job_id, poll it for running/completed/failed" (the
first was `ingestion.api`'s `/ingestion/historical`), so it's shared
code now instead of two copies of the same ~40 lines. Each router
keeps its own `JobTracker()` instance and shapes the poll response
into whatever fields make sense for its own domain.

### Usage: running a multi-chunk sequence by hand today

```bash
# Chunk 1: 2023, fresh start
curl -X POST "localhost:8001/forecasting/train-incremental-chunk?start_date=2023-01-01&end_date=2023-12-31"
# -> {"job_id": "job-1", ...}
curl localhost:8001/forecasting/train-incremental-chunk/job-1
# -> poll until status=="completed"; note result.run_id, call it RUN_2023

# Chunk 2: 2024, continuing from 2023's checkpoint
curl -X POST "localhost:8001/forecasting/train-incremental-chunk?start_date=2024-01-01&end_date=2024-12-31&prior_run_id=$RUN_2023"
# -> poll, note result.run_id as RUN_2024

# Chunk 3 (final): 2025, continuing, and THIS time promote if it wins
curl -X POST "localhost:8001/forecasting/train-incremental-chunk?start_date=2025-01-01&end_date=2025-12-31&prior_run_id=$RUN_2024&evaluate_and_promote=true"
```

Nothing here auto-sequences the chunks for you yet — you (or a script,
or a future cron) drive the loop, exactly as the "what's not built yet"
section below describes.

## What's implemented and tested

| Piece | File | Tests |
|---|---|---|
| Scaler reuse | `features.py` | `test_forecasting_features.py` (`test_given_scaler_is_used_verbatim_not_refit`) |
| Optimizer-state checkpointing in `train_model()` | `training/train.py` | `test_forecasting_train.py::TestCheckpointContinuation` (4 tests, including a deterministic zero-epoch proof that weights actually load, and an A/B proof that prior optimizer state changes the training trajectory) |
| `log_model_artifacts`/`load_checkpoint` | `mlops/registry.py` | `test_forecasting_registry.py::TestLoadCheckpoint` (real MLflow round-trips of weights/optimizer/scaler; graceful `None` when a run never logged optimizer state) |
| Date-scoped fetch | `data.py` | `test_forecasting_data.py` (since/until query building, combined with region filter) |
| Chunk orchestration | `training/incremental.py` | `test_forecasting_incremental.py` (8 tests: fresh-chunk, continuation, scaler-reuse-across-chunks, architecture-mismatch guard, MLflow lineage tags, evaluate_and_promote on/off — real `train_model()` + real MLflow, mocked `TrainingSetLoader.fetch`) |
| API endpoint | `forecasting/api.py` | `test_forecasting_api.py::TestTriggerTrainIncrementalChunk` (6 tests: trigger/poll/422/404/failure, mirroring `ingestion.api`'s pattern) |
| Shared job tracker | `shared/job_tracker.py` | `test_shared_job_tracker.py` (6 tests) |

Full repo `make test` (both services, 90% coverage gate): passing —
confirm the latest number by re-running `make test` from the repo root.

## What's NOT built yet

**1. Automatic multi-chunk sequencing.** Today you (or a script) call
`/forecasting/train-incremental-chunk` once per chunk and thread
`prior_run_id` through by hand. A real orchestrator would: read a list
of chunk boundaries (e.g. one per calendar year plus a final "current"
chunk), call the endpoint for each in order, poll until each completes,
and pass the previous chunk's `run_id` to the next automatically —
resumable (skip chunks whose checkpoint already exists, tracked via the
MLflow lineage tags) so a mid-sequence failure doesn't require
restarting from chunk 1.

**2. Purging old chunk data ("clean DB" in the original diagram).**
Nothing here deletes anything — `/ingestion/historical` only upserts.
A real purge needs:
  - Delete-by-date-range for the historical MongoDB collections (no
    delete path exists anywhere in `ingestion/` today, only upsert).
  - Delete-by-date-range for the corresponding warehouse Postgres rows
    (`ml_features_demand_v1` and whatever it's built from).
  - **A real subtlety to get right**: a lookback window needs
    `model_lookback` (default 48) steps of history immediately
    *preceding* a chunk's first row. If you purge a chunk's data
    completely before starting the next chunk, the next chunk's first
    `lookback` samples have no valid antecedent window — either accept
    a small amount of lost training data at each chunk boundary, or
    keep a small overlap buffer (the previous chunk's last `lookback`
    rows) instead of purging it. Decide deliberately; don't purge
    everything and quietly lose window continuity.

**3. `training/online.py`'s `fine_tune()` still resets Adam's
momentum every call** — the exact trap this whole document opened
with, still present in the *other* continuation path this repo has
(the periodic online-fine-tune cron job, distinct from year-chunk
training). `train_model()`'s new `initial_optimizer_state` mechanism
could be ported into `fine_tune()` too (same idea: persist+restore via
`log_model_artifacts`'s new `optimizer_state` param), closing this gap
for real-time online learning as well, not just chunked historical
training. Not done in this pass — flagged here so it doesn't get
lost.

**4. `tune.py` (Optuna search) has no checkpoint-continuation support**
— each trial trains a fresh model, appropriately, since HPO needs to
try genuinely different hyperparameters per trial. Not a gap, just
noting it's out of scope for this mechanism by design.

**5. CLI wiring.** Every other training capability in this repo
(`train`/`tune`/`evaluate`/`status`/`online-finetune`) has both a CLI
subcommand (`ecolens.forecasting.cli`) and (where relevant) an API
trigger. This pass only added the API trigger for incremental chunks —
a `python -m ecolens.forecasting.cli train-incremental-chunk` subcommand
wiring straight into `training/incremental.run_incremental_chunk` would
be a small, low-risk follow-up for parity, and for anyone who wants to
drive a chunk sequence from a shell script rather than curl.

**6. Colab GPU bridge integration.** `training/colab_dispatch.py`
(this repo's earlier Colab T4 bridge work) dispatches a single
`train_model()` call to a remote GPU kernel. It doesn't yet know about
`initial_model_state`/`initial_optimizer_state` — extending it to
accept and forward those (and to embed a `Checkpoint`'s state alongside
the dataset in the remote bundle) would let a chunk's continuation
training run on Colab's free T4 instead of local CPU, same as a single
`train_model()` call already can. Small, mechanical extension of
`_build_remote_script`, not attempted here.
