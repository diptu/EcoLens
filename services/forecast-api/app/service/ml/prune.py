"""Structured pruning + fine-tune recovery for `DemandLSTM`
(`todo-model-training.md` Phase 5).

**Scope, stated honestly**: LSTM only. TFT's interlinked VSN/GRN/
attention structure (`app/models/tft.py`) makes a correct structural
compaction meaningfully harder to get right (a subtly wrong compaction
is a silent-bad-predictions bug, not just a missing feature) — real,
deliberate future work, not silently implied as already covered here,
mirroring this same phase's own explicit TimesFM exemption ("used
frozen/zero-shot -- pruning a foundation-model checkpoint is a
materially different, much bigger undertaking... explicitly out of
scope").

**Why this isn't a literal `torch.nn.utils.prune.ln_structured` call,
despite this phase's own text naming it**: `ln_structured` prunes along
one flat tensor dimension, treating each slice independently. `nn.LSTM`'s
`weight_hh_l{layer}` is shaped `(4*hidden_size, hidden_size)` — the 4
gates (input/forget/cell/output) are stored as 4 stacked row-blocks, so
one logical "hidden unit" is actually 4 *non-contiguous* rows (at
offsets `j`, `hidden+j`, `2*hidden+j`, `3*hidden+j`). `ln_structured`
has no way to express "prune these 4 rows together, consistently, as one
unit" — it would prune individual gate-rows independently, which doesn't
correspond to removing a real hidden unit at all. This module computes
the same real idea `ln_structured` is built on (rank-by-Ln-norm,
structured/whole-unit removal, not scattered individual weights) via
`torch.norm` grouped correctly across all 4 gate blocks, then *physically
compacts* the tensors (not just zero-masks them) — the only way to get a
real parameter-count and on-disk-size reduction, not just a sparse
tensor of the same physical size. This phase's own module-docstring
language already anticipated exactly this distinction ("structured
pruning... matters... unstructured pruning doesn't actually reduce a
dense tensor's real inference latency without specialized sparse
kernels this stack doesn't have") — physical compaction is what makes
the structured/unstructured distinction actually pay off here.

**Mathematical correctness of "drop a unit", stated precisely**: for
unit `j` to be removable without changing every *other* unit's behavior,
two things must hold: (1) nothing downstream ever reads unit `j`'s
hidden state again -- satisfied by dropping row `j` (and its 3
gate-siblings) from `weight_hh_l{layer+1}`/`weight_ih_l{layer+1}`
(output side) and from the downstream heads that consume the final
layer's output (`attention.score`, `point_head`, etc.); (2) unit `j`'s
own state no longer influences anything -- satisfied by additionally
dropping column `j` from every `weight_hh_l{layer}` (a hidden unit
feeds into every gate's *input* at the next timestep via the column
space of `weight_hh`). Dropping both the row and column consistently
for every pruned unit is exactly "this unit doesn't exist" -- verified
directly in `tests/test_prune.py` by confirming `keep_fraction=1.0`
(prune nothing) reproduces the original model's outputs exactly.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from mlflow.tracking import MlflowClient

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.ml import DemandLSTM
from app.service.ml.data import load_holidays, load_training_data
from app.service.ml.evaluate import (
    LSTMForecaster,
    evaluate_walk_forward,
    load_registered_model,
)
from app.service.ml.features import build_features
from app.service.ml.train import TrainConfig, log_and_register_run, train_model
from app.service.mlops.tracking import configure_mlflow


def _unit_importance(weight_hh_l0: torch.Tensor, hidden_size: int) -> torch.Tensor:
    """Real per-unit L2-norm importance score, correctly grouped across
    `nn.LSTM`'s 4 interleaved gate row-blocks (see module docstring) --
    the same "rank by Ln norm, prune the lowest" idea
    `torch.nn.utils.prune.ln_structured` implements for a single flat
    dim, generalised to a unit's real 4-row identity in this tensor."""
    gates = weight_hh_l0.reshape(
        4, hidden_size, hidden_size
    )  # (gate, out_unit, in_unit)
    # A unit's real footprint spans both how it's computed (its row
    # across all 4 gates) and what it feeds into (its column across all
    # 4 gates) -- both included so a unit that's an important *input* to
    # other units, even if its own row weights are small, isn't
    # incorrectly ranked as prunable.
    row_norm = torch.norm(gates, p=2, dim=(0, 2))  # (hidden_size,)
    col_norm = torch.norm(gates, p=2, dim=(0, 1))  # (hidden_size,)
    return row_norm + col_norm


def _select_units_to_keep(
    state_dict: dict[str, torch.Tensor], hidden_size: int, keep_fraction: float
) -> torch.Tensor:
    if not (0.0 < keep_fraction <= 1.0):
        raise ValueError("keep_fraction must be in (0, 1]")
    n_keep = max(1, round(hidden_size * keep_fraction))
    importance = _unit_importance(state_dict["lstm.weight_hh_l0"], hidden_size)
    keep_idx = torch.argsort(importance, descending=True)[:n_keep]
    return torch.sort(keep_idx).values


def compact_lstm(
    model: DemandLSTM, keep_fraction: float
) -> tuple[DemandLSTM, torch.Tensor]:
    """Real structural compaction: builds a genuinely smaller
    `DemandLSTM` (`hidden_size = round(model.lstm.hidden_size *
    keep_fraction)`) and copies over exactly the surviving units' rows/
    columns for every affected tensor (`lstm.*`, `attention.score`, all
    3 output heads) -- not a zero-mask, a real shape change. Returns
    `(compacted_model, keep_idx)` -- `keep_idx` (the original model's
    unit indices that survived, ascending) is returned so a caller can
    verify/audit which units were kept, not just trust the count.

    `keep_fraction=1.0` is a real, exact no-op (verified in
    `tests/test_prune.py`): every unit "survives", and the returned
    model's weights equal the original's exactly.
    """
    hidden_size = model.lstm.hidden_size
    num_layers = model.lstm.num_layers
    state_dict = model.state_dict()
    keep_idx = _select_units_to_keep(state_dict, hidden_size, keep_fraction)
    n_keep = len(keep_idx)

    def _gate_rows(idx: torch.Tensor) -> torch.Tensor:
        """The 4 non-contiguous rows (one per gate) for each unit in
        `idx`, in `nn.LSTM`'s real row order (all of gate 0's rows, then
        all of gate 1's, ...) -- matches `weight_hh_l*`/`weight_ih_l*`'s
        actual on-disk row layout."""
        return torch.cat([idx + g * hidden_size for g in range(4)])

    gate_rows = _gate_rows(keep_idx)

    compacted = DemandLSTM(
        n_features=model.n_features,
        horizon=model.horizon,
        hidden_size=n_keep,
        num_layers=num_layers,
        dropout=model.lstm.dropout,
    )
    new_state = compacted.state_dict()

    for layer in range(num_layers):
        ih_key, hh_key = f"lstm.weight_ih_l{layer}", f"lstm.weight_hh_l{layer}"
        bih_key, bhh_key = f"lstm.bias_ih_l{layer}", f"lstm.bias_hh_l{layer}"

        weight_ih = state_dict[ih_key][gate_rows]
        if layer > 0:
            # Layers beyond the first take the *previous* (also pruned)
            # layer's hidden state as input, so the input dim is pruned
            # too -- layer 0's input is `n_features`, untouched.
            weight_ih = weight_ih[:, keep_idx]
        new_state[ih_key] = weight_ih
        new_state[hh_key] = state_dict[hh_key][gate_rows][:, keep_idx]
        new_state[bih_key] = state_dict[bih_key][gate_rows]
        new_state[bhh_key] = state_dict[bhh_key][gate_rows]

    new_state["attention.score.weight"] = state_dict["attention.score.weight"][
        :, keep_idx
    ]
    new_state["attention.score.bias"] = state_dict["attention.score.bias"]
    for head in ("point_head", "lower_spread_head", "upper_spread_head"):
        new_state[f"{head}.weight"] = state_dict[f"{head}.weight"][:, keep_idx]
        new_state[f"{head}.bias"] = state_dict[f"{head}.bias"]

    compacted.load_state_dict(new_state)
    # Real bug, confirmed live 2026-08-11 while adding `DemandLSTM.
    # head_dropout`: this function never propagated `model`'s train/eval
    # mode to the freshly-constructed `compacted` (which defaults to
    # `training=True`, `nn.Module`'s own default). Invisible until now
    # because the LSTM's only *previous* dropout site (its own inter-
    # layer `dropout=`) is a hard no-op whenever `num_layers=1` --
    # exactly the case `tests/test_prune.py`'s `keep_fraction=1.0` no-op
    # test happened to use. The moment a second, always-active dropout
    # site exists (`head_dropout`), a `compacted` left in training mode
    # would fire it stochastically even when `original_model` was
    # already `.eval()`'d (`prune_and_recover`'s caller always loads via
    # `load_registered_model`, which calls `.eval()`) -- silently
    # breaking the exact-output-match guarantee this function's own
    # docstring promises. Matching modes here is what keeps that
    # guarantee real regardless of how many dropout sites `DemandLSTM`
    # ever grows.
    compacted.train(model.training)
    return compacted, keep_idx


@dataclass
class PruneBenchmark:
    original_param_count: int
    pruned_param_count: int
    original_artifact_bytes: int
    pruned_artifact_bytes: int
    original_latency_ms: float
    pruned_latency_ms: float

    @property
    def param_reduction_pct(self) -> float:
        return 100.0 * (1 - self.pruned_param_count / self.original_param_count)

    @property
    def size_reduction_pct(self) -> float:
        return 100.0 * (1 - self.pruned_artifact_bytes / self.original_artifact_bytes)

    @property
    def latency_change_pct(self) -> float:
        """Negative means faster. CPU wall-clock latency is real but
        noisy (`benchmark_models`' own `n_repeats` averaging helps, but
        this is still a laptop/CI-shared-core measurement, not a
        controlled benchmark environment) -- treat small magnitudes as
        noise, not a real regression/win either way."""
        return 100.0 * (self.pruned_latency_ms / self.original_latency_ms - 1)

    def achieves_a_real_win(
        self,
        *,
        min_size_reduction_pct: float = 5.0,
        max_latency_regression_pct: float = 10.0,
    ) -> bool:
        """Real, honest acceptance check (`todo-model-training.md` Phase
        5's "only register/promote... if it actually achieves a measured
        latency/size win"): a meaningfully smaller artifact
        (`min_size_reduction_pct`, default 5%) that isn't meaningfully
        SLOWER (`max_latency_regression_pct`, default 10% -- CPU
        dense-matmul latency doesn't reliably shrink from fewer units
        the way size does, so this only guards against a real
        regression, not requiring an actual speedup)."""
        return (
            self.size_reduction_pct >= min_size_reduction_pct
            and self.latency_change_pct <= max_latency_regression_pct
        )


def _param_count(model: DemandLSTM) -> int:
    return sum(p.numel() for p in model.parameters())


def _artifact_bytes(model: DemandLSTM) -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "model.pt"
        torch.save(model.state_dict(), path)
        return path.stat().st_size


def _measure_latency_ms(
    model: DemandLSTM, lookback: int, n_features: int, *, n_repeats: int = 20
) -> float:
    """Real measured CPU inference latency (`time.perf_counter`), mean
    over `n_repeats` single-sample forward passes -- matches this
    stack's real serving environment (CPU, `forecast-api`'s own
    inference path), not a GPU number that doesn't transfer (this
    phase's own explicit framing)."""
    model.eval()
    x = torch.randn(1, lookback, n_features)
    with torch.no_grad():
        model(x)  # warm-up -- excludes one-time lazy-init cost from the measurement
        start = time.perf_counter()
        for _ in range(n_repeats):
            model(x)
        elapsed = time.perf_counter() - start
    return (elapsed / n_repeats) * 1000


def benchmark_models(
    original: DemandLSTM, pruned: DemandLSTM, lookback: int
) -> PruneBenchmark:
    """Real before/after benchmark (`todo-model-training.md` Phase 5):
    parameter count, on-disk artifact size (`torch.save`d state_dict,
    the same artifact `ml/train.py`'s `log_and_register_run` persists),
    and measured CPU inference latency -- logged to MLflow alongside the
    recovery fine-tune's own metrics by whichever caller orchestrates
    the full prune-then-recover-then-gate pipeline."""
    return PruneBenchmark(
        original_param_count=_param_count(original),
        pruned_param_count=_param_count(pruned),
        original_artifact_bytes=_artifact_bytes(original),
        pruned_artifact_bytes=_artifact_bytes(pruned),
        original_latency_ms=_measure_latency_ms(
            original, lookback, original.n_features
        ),
        pruned_latency_ms=_measure_latency_ms(pruned, lookback, pruned.n_features),
    )


@dataclass
class PruneAndRecoverResult:
    benchmark: PruneBenchmark
    recovered_run_id: str
    recovered_model_version: str | None
    recovered_test_mape: float | None
    unpruned_eval_mape: float
    recovered_eval_mape: float
    relative_mape_regression_pct: float
    achieves_size_latency_win: bool
    passes_accuracy_tolerance: bool
    gate_passed: bool


async def prune_and_recover(
    model_name: str,
    version: str | int,
    regions: Sequence[str],
    keep_fraction: float,
    *,
    settings: Settings | None = None,
    recovery_epochs: int | None = None,
    max_relative_mape_regression_pct: float = 1.0,
    n_origins: int = 5,
    register: bool = True,
) -> PruneAndRecoverResult:
    """The full real pipeline (`todo-model-training.md` Phase 5): loads
    a registered LSTM version, structurally compacts it
    (`compact_lstm`), benchmarks the real before/after
    (`benchmark_models`), recovery-fine-tunes the compacted model
    (reusing `ml/train.py`'s existing `train_model(...,
    warm_start_state_dict=...)` machinery -- the same warm-start
    mechanism `ml/incremental.py` already uses, just seeded from pruned
    weights instead of an unpruned Production version, per this phase's
    own "not a new training path" instruction), and gates registration
    on BOTH a real accuracy-tolerance check (walk-forward MAPE regression
    vs. the unpruned version, via Phase 0's `evaluate.py` harness -- not
    just training-time `test_mape`) and a real measured size/latency win
    (`PruneBenchmark.achieves_a_real_win`).

    `register=True` (the default) always registers the recovered version
    for auditability -- `gate_passed` is tagged on it
    (`prune_gate_passed`) so a human/`promote_version` can see the real
    outcome either way, matching this phase's own "the honest result is
    'pruning wasn't worth it at this model size', which is a legitimate
    real outcome to report, not a failure to hide" framing. Never
    promotes to Production itself, same as every other training path in
    this codebase.
    """
    settings = settings or get_settings()
    configure_mlflow(settings)

    forecaster = load_registered_model(model_name, version)
    original_model = forecaster.model
    lookback = forecaster.lookback

    compacted_model, keep_idx = compact_lstm(original_model, keep_fraction)
    benchmark = benchmark_models(original_model, compacted_model, lookback)

    async with get_session() as db:
        raw_df = await load_training_data(db, regions)
        holidays_df = await load_holidays(db)
    if raw_df.empty:
        raise ValueError(f"no data found in the warehouse for regions={list(regions)}")

    unpruned_engineered = build_features(raw_df, holidays=holidays_df)
    unpruned_reports = []
    for region in regions:
        region_df = (
            unpruned_engineered[unpruned_engineered["region"] == region]
            .sort_values("ts")
            .reset_index(drop=True)
        )
        if region_df.empty:
            continue
        unpruned_reports.append(
            evaluate_walk_forward(
                forecaster,
                region_df,
                original_model.horizon,
                n_origins=n_origins,
                min_history=lookback,
            )
        )

    unpruned_scored = [
        r for r in unpruned_reports if r.n_origins > 0 and not np.isnan(r.mape)
    ]
    unpruned_eval_mape = (
        float(np.mean([r.mape for r in unpruned_scored]))
        if unpruned_scored
        else float("nan")
    )

    config = TrainConfig.from_settings(settings)
    config.hidden_size = compacted_model.lstm.hidden_size
    config.num_layers = compacted_model.lstm.num_layers
    config.horizon = original_model.horizon
    config.lookback = lookback
    # Real bug, confirmed live 2026-08-11: this used to fall back to
    # `settings.incremental_train_epochs` (3) -- see `Settings.
    # prune_recovery_epochs`'s own docstring for the measured numbers
    # (3 epochs: +131.2% relative MAPE regression, ~131x past the 1%
    # gate below; 20: comfortably better than the unpruned version).
    if recovery_epochs is not None:
        config.epochs = recovery_epochs
    else:
        config.epochs = settings.prune_recovery_epochs
    config.lr = settings.incremental_train_lr

    recovered_result = train_model(
        raw_df,
        config,
        holidays=holidays_df,
        warm_start_state_dict=compacted_model.state_dict(),
    )

    # `train_model` (the LSTM-specific trainer this function always calls
    # above) always produces a real `DemandLSTM` in `TrainResult.model` --
    # that field is typed as the more general `nn.Module` only because
    # `TrainResult` is shared with `train_tft.py` (see that field's own
    # comment in `train.py`).
    assert isinstance(recovered_result.model, DemandLSTM)  # nosec B101 -- narrows a real, always-true invariant of train_model's own return contract, not a security check
    recovered_forecaster = LSTMForecaster(
        model=recovered_result.model,
        feature_scalers=recovered_result.feature_scalers,
        target_scaler=recovered_result.target_scaler,
        lookback=lookback,
        calibration=recovered_result.calibration,
        name=f"{model_name}_pruned_candidate",
    )
    recovered_reports = []
    for region in regions:
        region_df = (
            unpruned_engineered[unpruned_engineered["region"] == region]
            .sort_values("ts")
            .reset_index(drop=True)
        )
        if region_df.empty:
            continue
        recovered_reports.append(
            evaluate_walk_forward(
                recovered_forecaster,
                region_df,
                original_model.horizon,
                n_origins=n_origins,
                min_history=lookback,
            )
        )
    recovered_scored = [
        r for r in recovered_reports if r.n_origins > 0 and not np.isnan(r.mape)
    ]
    recovered_eval_mape = (
        float(np.mean([r.mape for r in recovered_scored]))
        if recovered_scored
        else float("nan")
    )

    relative_regression_pct = (
        100.0 * (recovered_eval_mape - unpruned_eval_mape) / unpruned_eval_mape
        if unpruned_eval_mape
        and not np.isnan(unpruned_eval_mape)
        and not np.isnan(recovered_eval_mape)
        else float("inf")
    )
    passes_accuracy_tolerance = (
        relative_regression_pct <= max_relative_mape_regression_pct
    )
    achieves_win = benchmark.achieves_a_real_win()
    gate_passed = passes_accuracy_tolerance and achieves_win

    log_result = log_and_register_run(
        recovered_result,
        config,
        regions,
        model_name,
        register=register,
        extra_tags={
            "training_type": "pruned_recovery",
            "pruned_from_run_id": forecaster.name,
            "pruned_from_version": str(version),
        },
        extra_params={
            "keep_fraction": keep_fraction,
            "n_units_kept": len(keep_idx),
            "original_param_count": benchmark.original_param_count,
            "pruned_param_count": benchmark.pruned_param_count,
            "param_reduction_pct": benchmark.param_reduction_pct,
            "size_reduction_pct": benchmark.size_reduction_pct,
            "latency_change_pct": benchmark.latency_change_pct,
            "unpruned_eval_mape": unpruned_eval_mape,
            "recovered_eval_mape": recovered_eval_mape,
            "relative_mape_regression_pct": relative_regression_pct,
            "prune_gate_passed": gate_passed,
        },
    )

    if register and log_result.model_version:
        client = MlflowClient()
        client.set_model_version_tag(
            model_name, log_result.model_version, "prune_gate_passed", str(gate_passed)
        )

    return PruneAndRecoverResult(
        benchmark=benchmark,
        recovered_run_id=log_result.run_id,
        recovered_model_version=log_result.model_version,
        recovered_test_mape=recovered_result.test_metrics.get("test_mape"),
        unpruned_eval_mape=unpruned_eval_mape,
        recovered_eval_mape=recovered_eval_mape,
        relative_mape_regression_pct=relative_regression_pct,
        achieves_size_latency_win=achieves_win,
        passes_accuracy_tolerance=passes_accuracy_tolerance,
        gate_passed=gate_passed,
    )
