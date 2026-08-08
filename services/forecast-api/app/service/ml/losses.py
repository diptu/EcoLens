"""Loss functions for `DemandLSTM` (`README.md`: "Huber (robust to
dispatch spikes), with a separate pinball loss branch for 10/90 quantile
heads") and `EnergyForecastLSTM` (`app/models/energy_forecast_lstm.py`,
the multi-task demand + generation-mix model).
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
    huber_delta: float = HUBER_DELTA,
    quantile_weight: float = 1.0,
) -> Tensor:
    """The full training objective: Huber on the P50 point head plus
    `quantile_weight`-scaled pinball loss on each of the P10/P90 spread
    heads. `quantile_weight` defaults to `1.0` (equal weighting) --
    `ml/train.py` exposes it as a tunable hyperparameter for `make tune`."""
    point = huber_loss(forecast.p50, target, delta=huber_delta)
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
