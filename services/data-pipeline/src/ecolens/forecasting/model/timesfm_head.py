"""The trainable half of this repo's TimesFM path -- root TODO.md's
"Stand up TimesFM: Frozen transformer backbone, head-only training."

`TimesFMCalibrationHead` is a small, genuinely-trained `nn.Module`: it
never sees TimesFM's weights or internals, only the frozen backbone's
already-computed `(p10, p50, p90)` output (see
`service/timesfm_backbone.py`) plus a region embedding, and learns a
per-horizon-step additive correction on top of each. Starting from
TimesFM's own point/quantile forecasts (rather than learning demand
prediction from scratch) is a real inductive-bias choice: the frozen
foundation model has already done the hard work, so this head only has
to learn *where that raw forecast tends to be off* for this repo's
specific data -- both point-forecast bias (region-specific offsets, e.g.
NEM vs. WEM baseline demand differ hugely) and interval bias.

`forward()` returns the same `{"p50", "p10", "p90"}` dict shape as
`DemandLSTM`/`DemandTFT`, so `training/losses.py`'s `DemandForecastLoss`
needs no changes at all.

Operates entirely in this repo's existing *scaled* space (the same
`FeatureScaler`-normalized units `DemandLSTM`/`DemandTFT` already train
against), not raw MW -- `training/train_timesfm.py` normalizes TimesFM's
raw MW-scale output before it ever reaches this module. Training a
Huber/pinball loss (`DemandForecastLoss`, `delta=1.0`) against raw
thousands-of-MW values would leave gradients scaled by an arbitrary,
target-dependent magnitude for no benefit -- same reasoning
`schema/features.py`'s `Split` docstring already gives for why LSTM/TFT
train in scaled space to begin with. `service/evaluation/evaluate_timesfm.py`
inverse-transforms this head's output back to MW before conformal
calibration/metrics, exactly like `predict_split`/`predict_split_tft`
already do for the other two models.
"""

from __future__ import annotations

import torch
from torch import nn


class TimesFMCalibrationHead(nn.Module):
    def __init__(
        self,
        *,
        horizon: int,
        num_regions: int,
        static_dim: int,
        hidden_dim: int,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.horizon = horizon
        self.num_regions = num_regions
        self.static_dim = static_dim
        self.hidden_dim = hidden_dim
        self.dropout = dropout

        self.region_embedding = nn.Embedding(num_regions, static_dim)
        self.net = nn.Sequential(
            nn.Linear(3 + static_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Dropout(dropout),
        )
        self.correction_p50 = nn.Linear(hidden_dim, 1)
        self.correction_p10 = nn.Linear(hidden_dim, 1)
        self.correction_p90 = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        raw_p10: torch.Tensor,
        raw_p50: torch.Tensor,
        raw_p90: torch.Tensor,
        region_idx: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        """`raw_p10`/`raw_p50`/`raw_p90`: `(batch, horizon)`, TimesFM's own
        frozen output, already scaled into this repo's normalized units
        (see module docstring). `region_idx`: `(batch,)` LongTensor.
        """
        batch, horizon = raw_p50.shape
        static = self.region_embedding(region_idx)  # (batch, static_dim)
        static = static.unsqueeze(1).expand(-1, horizon, -1)

        stacked = torch.stack(
            [raw_p10, raw_p50, raw_p90], dim=-1
        )  # (batch, horizon, 3)
        features = torch.cat([stacked, static], dim=-1)
        hidden = self.net(features)  # (batch, horizon, hidden_dim)

        return {
            "p50": raw_p50 + self.correction_p50(hidden).squeeze(-1),
            "p10": raw_p10 + self.correction_p10(hidden).squeeze(-1),
            "p90": raw_p90 + self.correction_p90(hidden).squeeze(-1),
        }

    def architecture_dict(self) -> dict[str, int | float]:
        """Mirrors `DemandLSTM`/`DemandTFT`'s `architecture_dict()` -- the
        constructor kwargs needed to reconstruct an empty instance for
        `state_dict` loading (see `mlops/registry.py`). Deliberately does
        *not* include anything about TimesFM itself -- this head has no
        dependency on which TimesFM checkpoint produced its inputs, only
        on their shape.
        """
        return {
            "horizon": self.horizon,
            "num_regions": self.num_regions,
            "static_dim": self.static_dim,
            "hidden_dim": self.hidden_dim,
            "dropout": self.dropout,
        }


__all__ = ["TimesFMCalibrationHead"]
