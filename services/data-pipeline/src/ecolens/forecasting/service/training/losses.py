"""ECO-112 (loss functions): Huber loss for the point forecast, pinball
(quantile) loss for the P10/P90 heads that `evaluation/conformal.py`
will calibrate later.
"""

from __future__ import annotations

import torch
from torch import nn


def pinball_loss(
    preds: torch.Tensor, target: torch.Tensor, quantile: float
) -> torch.Tensor:
    """Quantile ("pinball") loss: asymmetric penalty that pushes `preds`
    toward the `quantile`-th conditional quantile of `target`, not the
    mean. `quantile=0.5` degenerates to (half) MAE.
    """
    diff = target - preds
    return torch.mean(torch.maximum(quantile * diff, (quantile - 1) * diff))


class DemandForecastLoss(nn.Module):
    """Combines the three heads into one scalar: Huber on P50 (robust to
    the occasional demand spike/outage outlier) plus pinball on P10/P90,
    weighted down so the point forecast — what most consumers of this
    model care about first — dominates early training.
    """

    def __init__(
        self,
        *,
        huber_delta: float = 1.0,
        quantile_low: float = 0.1,
        quantile_high: float = 0.9,
        quantile_weight: float = 0.5,
    ) -> None:
        super().__init__()
        self.huber = nn.HuberLoss(delta=huber_delta)
        self.quantile_low = quantile_low
        self.quantile_high = quantile_high
        self.quantile_weight = quantile_weight

    def forward(
        self, outputs: dict[str, torch.Tensor], target: torch.Tensor
    ) -> tuple[torch.Tensor, dict[str, float]]:
        point_loss = self.huber(outputs["p50"], target)
        low_loss = pinball_loss(outputs["p10"], target, self.quantile_low)
        high_loss = pinball_loss(outputs["p90"], target, self.quantile_high)
        total = point_loss + self.quantile_weight * (low_loss + high_loss)
        components = {
            "point_loss": point_loss.item(),
            "pinball_low": low_loss.item(),
            "pinball_high": high_loss.item(),
        }
        return total, components


__all__ = ["pinball_loss", "DemandForecastLoss"]
