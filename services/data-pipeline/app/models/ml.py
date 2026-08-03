"""`DemandLSTM` — the demand-forecasting model (ECO-D50, `README.md`'s
"Demand forecasting (PyTorch LSTM)" section, `TODO.md`'s Forecasting
section item 2).

**Design reconciliation** (`TODO.md`'s item 1, "pick the real v0
target"): `overview.md` describes a 3-model blend (LSTM + TFT + TimesFM)
with continuous online learning and self-correction — a much bigger scope
than anything else in this repo actually commits to building.
`docs/training-strategy.md` and `README.md`'s own "ML pipeline" section
both independently describe a single incremental LSTM, and
`README.md`'s Roadmap stages a baseline LSTM before anything multivariate
or blended. **This is that single LSTM** — the real v0 target. TFT/
TimesFM and true online/incremental training (this module trains from a
static snapshot, per-run, not continuously) are out of scope for this
pass; see `TODO.md` for that gap tracked honestly rather than silently
dropped.

Architecture, matching `README.md`'s spec exactly:

    2-layer nn.LSTM (hidden=128, dropout=0.2)
      -> additive attention pooling over the lookback timesteps
      -> FC head(s) producing `horizon`-step output

Three heads share the attention-pooled context vector: a point (P50)
head, plus two non-negative *spread* heads for the P10/P90 quantiles,
parameterised as `point - softplus(delta_low)` / `point +
softplus(delta_high)` rather than three independent linear heads. This
guarantees `p10 <= p50 <= p90` by construction from the first forward
pass — three unconstrained heads trained independently can (and in
practice do, early in training) cross, which would be a nonsensical
prediction interval. `pipeline.conformal`'s post-hoc calibration widens
these further to hit actual target coverage; it doesn't fix crossing,
so this module removes that failure mode structurally instead.
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import Tensor, nn


@dataclass
class DemandForecast:
    """One forward pass's output — each field shaped `(batch, horizon)`."""

    p10: Tensor
    p50: Tensor
    p90: Tensor


class AttentionPool(nn.Module):
    """Additive (Bahdanau-style) attention pooling: a learned scalar score
    per timestep, softmax-normalised over the lookback window, used to
    take a weighted sum of the LSTM's per-timestep hidden states into one
    context vector — instead of just using the last timestep's hidden
    state, which discards everything the LSTM saw earlier in the window."""

    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        self.score = nn.Linear(hidden_size, 1)

    def forward(self, lstm_out: Tensor) -> Tensor:
        # lstm_out: (batch, lookback, hidden_size)
        scores = self.score(lstm_out).squeeze(-1)  # (batch, lookback)
        weights = torch.softmax(scores, dim=1).unsqueeze(-1)  # (batch, lookback, 1)
        return (lstm_out * weights).sum(dim=1)  # (batch, hidden_size)


class DemandLSTM(nn.Module):
    def __init__(
        self,
        n_features: int,
        horizon: int = 48,
        hidden_size: int = 128,
        num_layers: int = 2,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.n_features = n_features
        self.horizon = horizon

        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            batch_first=True,
        )
        self.attention = AttentionPool(hidden_size)
        self.point_head = nn.Linear(hidden_size, horizon)
        self.lower_spread_head = nn.Linear(hidden_size, horizon)
        self.upper_spread_head = nn.Linear(hidden_size, horizon)

    def forward(self, x: Tensor) -> DemandForecast:
        """`x`: `(batch, lookback, n_features)` -> a `DemandForecast` of
        `(batch, horizon)` tensors, `p50` in the model's native (scaled)
        target units."""
        lstm_out, _ = self.lstm(x)
        context = self.attention(lstm_out)
        p50 = self.point_head(context)
        lower_spread = torch.nn.functional.softplus(self.lower_spread_head(context))
        upper_spread = torch.nn.functional.softplus(self.upper_spread_head(context))
        return DemandForecast(p10=p50 - lower_spread, p50=p50, p90=p50 + upper_spread)
