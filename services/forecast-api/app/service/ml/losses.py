"""Loss functions for `DemandLSTM`/`DemandTFT` and `EnergyForecastLSTM`
(`app/models/energy_forecast_lstm.py`, the multi-task demand +
generation-mix model).

**2026-08-12, `demand_loss`'s P50 term changed from Huber to true
pinball(0.5)** -- see `services/forecast-api/TODO.md` Phase 1 for the
full real-evidence writeup (real per-region walk-forward bias measured
as large as -343 MW, in both signs depending on region; Huber trains
toward the conditional *mean*, not the median, and does so unevenly
across regions because the target scaler is pooled, not per-region).
`energy_forecast_loss` below already used true pinball(0.5) for its own
point estimate before this change -- `demand_loss` now matches that
already-proven pattern instead of being the odd one out. `README.md`'s
"Huber (robust to dispatch spikes)" description of `DemandLSTM`'s
training is stale as of this change; not updated here since this file
doesn't own that doc.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor

from app.models.energy_forecast_lstm import P10, P50, P90, EnergyForecast
from app.models.ml import DemandForecast

# `EnergyForecast.demand`/`.generation`'s trailing-dim quantile levels,
# indexed the same way as `P10`/`P50`/`P90` (0/1/2).
ENERGY_QUANTILES: tuple[float, float, float] = (0.10, 0.50, 0.90)

HUBER_DELTA = 1.0
LOWER_QUANTILE = 0.1
UPPER_QUANTILE = 0.9


def huber_loss(pred: Tensor, target: Tensor, delta: float = HUBER_DELTA) -> Tensor:
    """Quadratic near zero, linear past `delta` -- robust to the large,
    sudden dispatch-price/demand spikes AEMO data is known for, versus a
    plain MSE loss that a single spike would dominate."""
    return F.huber_loss(pred, target, delta=delta)


def pinball_loss(pred: Tensor, target: Tensor, quantile: float) -> Tensor:
    """The standard quantile ("pinball") loss: asymmetric absolute error
    that penalises under-prediction more heavily for `quantile > 0.5` and
    over-prediction more heavily for `quantile < 0.5`, so minimising it
    drives `pred` toward the true `quantile`-th conditional quantile of
    `target`."""
    error = target - pred
    return torch.maximum(quantile * error, (quantile - 1) * error).mean()


def demand_loss(
    forecast: DemandForecast,
    target: Tensor,
    *,
    quantile_weight: float = 1.0,
) -> Tensor:
    """The full training objective: true pinball(0.5) on the P50 point
    head plus `quantile_weight`-scaled pinball loss on each of the P10/
    P90 spread heads -- all three heads now trained with the same loss
    family, just at different quantile levels (0.1/0.5/0.9). `quantile_
    weight` defaults to `1.0` (equal weighting) -- `ml/train.py` exposes
    it as a tunable hyperparameter for `make tune`; it only ever scaled
    the P10/P90 terms, never P50's, unchanged by this function's own
    2026-08-12 Huber -> pinball(0.5) switch (module docstring has the
    real evidence).

    No `huber_delta` param anymore -- confirmed unused by every real
    caller (`train.py`/`train_tft.py` never passed it), and the point
    head no longer calls `huber_loss` at all. `huber_loss` itself stays
    defined below (still real, still tested) in case a future tuning
    experiment wants it back; this function just doesn't call it."""
    point = pinball_loss(forecast.p50, target, 0.5)
    lower = pinball_loss(forecast.p10, target, LOWER_QUANTILE)
    upper = pinball_loss(forecast.p90, target, UPPER_QUANTILE)
    return point + quantile_weight * (lower + upper)


def _stacked_quantile_pinball_loss(pred: Tensor, target: Tensor) -> Tensor:
    """Sum of `pinball_loss` across `pred`'s trailing `[..., 3]`
    `P10`/`P50`/`P90` dim against a single `target` of `pred`'s shape
    minus that trailing dim (e.g. `pred: (B,H,3)` vs `target: (B,H)`, or
    `pred: (B,H,S,3)` vs `target: (B,H,S)`).

    Reuses the same `pinball_loss` this module already defines and tests
    for `DemandLSTM`'s separate-field quantiles -- `EnergyForecastLSTM`'s
    heads just stack the three quantiles on a trailing dim instead of
    three dataclass fields (see `app/models/energy_forecast_lstm.py`'s
    module docstring for why), so this is the same loss applied per
    slice, not a different formula.
    """
    losses = [
        pinball_loss(pred[..., idx], target, quantile)
        for idx, quantile in zip((P10, P50, P90), ENERGY_QUANTILES)
    ]
    return torch.stack(losses).sum()


def energy_forecast_loss(
    forecast: EnergyForecast,
    demand_target: Tensor,
    generation_target: Tensor,
    *,
    demand_weight: float = 1.0,
    generation_weight: float = 1.0,
) -> dict[str, Tensor]:
    """Combined training objective for `EnergyForecastLSTM`: pinball loss
    (all 3 quantiles) on demand, plus pinball loss on generation-mix.

    `demand_target`: `(B, H)`. `generation_target`: `(B, H, sources)`,
    same source order as `EnergyForecast.generation`'s `sources` dim
    (`GENERATION_SOURCES`).

    Deliberately compares *raw* model output against target -- not the
    reconciled-to-sum-to-demand generation `app/service/ml/
    reconciliation.reconcile_generation` produces. Reconciliation is a
    serving-time-only step (forecast-api, at inference) in this design;
    training the generation head against its own raw, unreconciled
    output keeps the two per-source quantile heads independently
    calibrated against real per-fuel history, rather than training
    against a target that's already been rescaled by whatever the
    demand head happened to predict in the same forward pass.
    """
    demand_loss_value = _stacked_quantile_pinball_loss(forecast.demand, demand_target)
    generation_loss_value = _stacked_quantile_pinball_loss(forecast.generation, generation_target)
    total = demand_weight * demand_loss_value + generation_weight * generation_loss_value
    return {
        "total_loss": total,
        "demand_loss": demand_loss_value,
        "generation_loss": generation_loss_value,
    }
