"""Generation/demand reconciliation — serving-time-only (`app/models/
energy_forecast_lstm.py`'s module docstring, and `service/ml/losses.
energy_forecast_loss`'s own docstring on `data-pipeline`): training never
calls this, only inference does.

`EnergyForecastLSTM` forecasts demand and per-source generation
independently, so they don't naturally sum to the same value. This
scales the predicted generation mix proportionally so
`sum(generation) == demand`, preserving the model's predicted
*composition* (relative shares between coal/gas/wind/solar/other) while
enforcing an energy-balance constraint a physically real grid always
satisfies. A practical V1 strategy, not the only one possible —
optimization-based or probabilistic reconciliation could replace this
layer later without changing its call signature.
"""

from __future__ import annotations

import torch
from torch import Tensor


def reconcile_generation(demand: Tensor, generation: Tensor) -> Tensor:
    """`demand`: `(B, H, Q)`. `generation`: `(B, H, S, Q)`. Returns
    `generation` rescaled per-`(batch, horizon, quantile)` so it sums to
    `demand` across the source dim -- same relative per-source shares,
    different absolute magnitude."""
    generation_total = generation.sum(dim=2)  # [B, H, Q]
    generation_total = torch.clamp(generation_total, min=1e-6)  # avoid /0

    scale = (demand / generation_total).unsqueeze(2)  # [B, H, 1, Q]
    return generation * scale
