"""Loss functions for `DemandLSTM` (`README.md`: "Huber (robust to
dispatch spikes), with a separate pinball loss branch for 10/90 quantile
heads").
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor

from app.models.ml import DemandForecast

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
