"""TimesFM adapter (`todo-model-training.md` Phase 1) — Google's
time-series foundation model, wrapped behind `service/ml/evaluate.py`'s
`Forecaster` protocol so it plugs into the exact same walk-forward
harness `BaselineForecaster`/`LSTMForecaster` already use, with zero
harness changes. Zero-shot: no training loop, no MLflow-registered
weights (there's nothing *we* produced to version — the checkpoint is
versioned by its own pinned HuggingFace revision, logged as a tag on
every evaluation run instead).

**Checkpoint note, stated honestly rather than silently substituted:**
`todo-model-training.md` named `google/timesfm-2.0-500m-pytorch`
(TimesFM 2.0) as the target checkpoint. The `timesfm` PyPI package
actually installable at implementation time (`timesfm==2.0.2`) ships
TimesFM **2.5**, whose only bundled/default checkpoint is
`google/timesfm-2.5-200m-pytorch` (200M params, not 500M) — there is no
2.0-architecture checkpoint importable through this package version.
Per the plan's own explicit allowance ("or the current recommended
checkpoint at implementation time"), this adapter uses the real,
current default. `TIMESFM_REVISION` below pins the exact HuggingFace
commit SHA actually downloaded, not a floating `main` ref.

**Frequency/cadence mapping, stated honestly rather than assumed:**
`todo-model-training.md` also assumed TimesFM's older (1.x/2.0) API,
which took an explicit per-series `freq` bucket (0=high/1=medium/
2=low frequency) that silently degrades accuracy if set wrong. The
actual installed 2.5 API (`ForecastConfig`, inspected directly against
`timesfm==2.0.2`'s real source) has **no `freq` parameter at all** —
2.5 dropped it. The analogous real risk in this version isn't a wrong
bucket, it's `max_context` too small to span this domain's real daily
seasonality: NEM's 5-min cadence needs `max_context >= 288` to see one
full day of history, WEM's 30-min cadence needs `>= 48` for the same.
`DEFAULT_MAX_CONTEXT` below is set generously above both.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from app.service.ml.features import TARGET_COLUMN

if TYPE_CHECKING:
    from timesfm import TimesFM_2p5_200M_torch

TIMESFM_REPO_ID = "google/timesfm-2.5-200m-pytorch"
# Exact commit this adapter was built/tested against (`huggingface.co/api/
# models/google/timesfm-2.5-200m-pytorch` at implementation time) — pinned
# so a future upstream update to the default checkpoint can't silently
# change this adapter's real accuracy out from under it.
TIMESFM_REVISION = "1d952420fba87f3c6dee4f240de0f1a0fbc790e3"

# Generously above both NEM's (5-min -> 288 steps/day) and WEM's (30-min
# -> 48 steps/day) real daily-seasonality span — see module docstring.
DEFAULT_MAX_CONTEXT = 512
# The real, installed 2.5 checkpoint silently rounds `max_horizon` UP to
# the nearest multiple of its 128-step output patch size at compile time
# (confirmed live: compiling with 64 logs "Using max horizon = 128
# instead.") -- set to 128 directly so `TimesFMForecaster.max_horizon`
# (used for this adapter's own `horizon > max_horizon` check) matches
# what the compiled model actually accepts, not what was asked for.
DEFAULT_MAX_HORIZON = 128

# TimesFM 2.5's `forecast()` returns `quantile_forecast` shaped
# `(batch, horizon, 10)`: column 0 is the model's mean estimate, columns
# 1-9 are the deciles [0.1, 0.2, ..., 0.9] in order (confirmed directly
# against the real model's output at implementation time — column 5's
# values matched `point_forecast` exactly, as expected for the median).
# Not documented as a stable public constant by the `timesfm` package
# itself, so pinned here explicitly rather than assumed silently.
_P10_COLUMN = 1
_P50_COLUMN = 5
_P90_COLUMN = 9


@dataclass
class TimesFMForecaster:
    """Wraps a loaded+compiled `TimesFM_2p5_200M_torch` behind the
    `Forecaster` protocol (`service/ml/evaluate.py`). Zero-shot univariate:
    feeds only `TARGET_COLUMN`'s real history, not the full engineered
    `FEATURE_COLUMNS` set `DemandLSTM` trains on — TimesFM's covariate
    path (`forecast_with_covariates`) exists but is deliberately not used
    here, matching Phase 1's "no training step" framing; a covariate-aware
    TimesFM evaluation is real future work, not silently implied by this
    adapter's honest P50 currently being weather/generation-mix-blind
    where the LSTM isn't.
    """

    model: "TimesFM_2p5_200M_torch"
    max_horizon: int
    name: str = "timesfm"
    target_col: str = TARGET_COLUMN

    def predict(
        self, history: pd.DataFrame, horizon: int
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        if horizon > self.max_horizon:
            raise ValueError(
                f"{self.name}: compiled with max_horizon={self.max_horizon}, "
                f"can't forecast horizon={horizon}"
            )
        series = history[self.target_col].dropna().to_numpy(dtype=np.float64)
        if series.size == 0:
            return (np.full(horizon, np.nan),) * 3

        _, quantiles = self.model.forecast(horizon=horizon, inputs=[series])
        p10 = quantiles[0, :, _P10_COLUMN]
        p50 = quantiles[0, :, _P50_COLUMN]
        p90 = quantiles[0, :, _P90_COLUMN]
        return p10, p50, p90


_OUTPUT_PATCH_SIZE = 128


def _round_up_to_output_patch(max_horizon: int) -> int:
    """The real, installed 2.5 checkpoint silently rounds `max_horizon` UP
    to the nearest multiple of its 128-step output patch size at compile
    time (confirmed live: compiling with 64 logs "Using max horizon = 128
    instead."). Mirrored here so `TimesFMForecaster.max_horizon` — used by
    its own `horizon > max_horizon` guard — always matches what the
    compiled model actually accepts, not what was asked for; without this,
    a caller requesting exactly 128 after asking for 64 would incorrectly
    be rejected by the adapter despite the compiled model handling it
    fine."""
    return (
        (max_horizon + _OUTPUT_PATCH_SIZE - 1) // _OUTPUT_PATCH_SIZE
    ) * _OUTPUT_PATCH_SIZE


@lru_cache(maxsize=1)
def load_timesfm_forecaster(
    max_context: int = DEFAULT_MAX_CONTEXT,
    max_horizon: int = DEFAULT_MAX_HORIZON,
) -> TimesFMForecaster:
    """Downloads (if not already cached) and compiles the pinned TimesFM
    checkpoint. Expensive (real HF download the first time, a real
    torch-compile step every time) — call once and reuse the returned
    `TimesFMForecaster` across every `evaluate_walk_forward` origin,
    exactly like `LSTMForecaster` reuses one loaded `DemandLSTM`.

    `@lru_cache`-backed (real OOM, confirmed live 2026-08-15: `train-
    worker` killed by the OOM reaper mid-download of a *second* 200M-
    param checkpoint for the next incremental `timesfm_correction`
    trigger, immediately after finishing the previous one). This
    function's own docstring already documented "call once and reuse" as
    the contract, but its real callers (`timesfm_correction.
    train_and_register_correction` and `.load_registered_correction_
    model`) each called it fresh on every invocation instead -- and
    `train-worker` is a single long-running process consuming one
    training-trigger message at a time (`db.rabbitmq.
    consume_training_trigger_events`'s `prefetch_count=1`, strictly
    sequential), so every automatic post-dbt-build `timesfm_correction`
    trigger downloaded+compiled a brand-new checkpoint that the previous
    one's memory was never reclaimed for -- the frozen base model never
    changes between calls (this module's own docstring: "no training
    loop, no MLflow-registered weights"), so there was never a
    correctness reason to reload it. Caching here, at the one real
    loader both call sites already funnel through, fixes both without
    touching either caller. `maxsize=1` (tightened from an initial `4`,
    2026-08-21): every real call site inside `train-worker` passes the
    same `(max_context, max_horizon)` pair in normal automatic
    operation, so a higher `maxsize` bought no real cache-hit benefit
    there while still permitting multiple 200M-param compiled models
    (several GB combined) to stay resident at once if anything ever did
    call with a different pair -- `1` caps this function's own
    worst-case memory contribution to exactly one resident copy, at the
    cost of a recompile (slow, not wrong) on a genuine param change.
    """
    import timesfm

    resolved_max_horizon = _round_up_to_output_patch(max_horizon)

    model = timesfm.TimesFM_2p5_200M_torch.from_pretrained(
        TIMESFM_REPO_ID, revision=TIMESFM_REVISION
    )
    model.compile(
        timesfm.ForecastConfig(
            max_context=max_context,
            max_horizon=resolved_max_horizon,
            normalize_inputs=True,
            use_continuous_quantile_head=False,
            fix_quantile_crossing=True,
        )
    )
    return TimesFMForecaster(model=model, max_horizon=resolved_max_horizon)
