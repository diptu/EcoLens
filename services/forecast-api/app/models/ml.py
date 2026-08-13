"""`DemandLSTM` — **intentionally duplicated, byte-for-byte, from
`data-pipeline`'s `app.models.ml`**.

Why duplicated rather than imported: `data-pipeline` trains and pickles
this class via `mlflow.pytorch.log_model`, but that pickle needs the
exact class importable by module path wherever it's unpickled — a
fragile, version-sensitive cross-service coupling this service
deliberately avoids (see `service/ml/registry.py`'s docstring). Instead,
`data-pipeline` also persists a plain `state_dict` (`docs/training-
strategy.md`'s documented "Model Portability Strategy") plus the
architecture hyperparams as MLflow run params; this service reconstructs
`DemandLSTM` from its own copy of the class and loads those weights in —
no dependency on `data-pipeline`'s package at runtime.

**This means the two copies must be kept in sync by hand** — a real,
accepted maintenance cost of the decoupling, not an oversight. A shared
internal package (both services depending on a small `ecolens-ml-core`
library) is the principled fix; deferred, see `TODO.md`'s Forecasting
section.

**2026-08-11 update**: training itself has since migrated into this
service (`app/core/config.py`'s own "ML training tunables -- ported from
data-pipeline... this service trains now, not just serves" comment;
`ml/train.py`/`ml/prune.py`/`cli.py`'s `train`/`train-tft`/`prune`
commands all live here), and no `data-pipeline` checkout exists in this
monorepo -- the sync-by-hand relationship this docstring describes may
no longer have a live counterpart to sync with. Left as historical
context rather than deleted (a real prior constraint, and still
accurate if a separate `data-pipeline` repo is active elsewhere); verify
before treating it as still load-bearing.
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
    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        self.score = nn.Linear(hidden_size, 1)

    def forward(self, lstm_out: Tensor) -> Tensor:
        scores = self.score(lstm_out).squeeze(-1)
        weights = torch.softmax(scores, dim=1).unsqueeze(-1)
        return (lstm_out * weights).sum(dim=1)


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
        # Real bug, confirmed live 2026-08-11 (real per-epoch MLflow
        # curves, `run c0030799`): `nn.LSTM`'s own `dropout=` kwarg above
        # is the *only* regularization anywhere in this forward pass --
        # `AttentionPool` and all three heads below had none, so nothing
        # regularized the exact point where the model commits to its
        # final prediction. Reuses the same `dropout` value (no new
        # constructor arg, no new `Settings`/`TrainConfig` field, no new
        # MLflow param) -- `nn.Dropout` has no learnable parameters, so
        # this adds zero new `state_dict` keys: safe for `ml/prune.py`'s
        # `compact_lstm` (never touches this key) and safe for loading
        # any already-registered older version (nothing to mismatch).
        self.head_dropout = nn.Dropout(dropout)
        self.point_head = nn.Linear(hidden_size, horizon)
        self.lower_spread_head = nn.Linear(hidden_size, horizon)
        self.upper_spread_head = nn.Linear(hidden_size, horizon)

    def forward(self, x: Tensor) -> DemandForecast:
        lstm_out, _ = self.lstm(x)
        context = self.head_dropout(self.attention(lstm_out))
        p50 = self.point_head(context)
        lower_spread = torch.nn.functional.softplus(self.lower_spread_head(context))
        upper_spread = torch.nn.functional.softplus(self.upper_spread_head(context))
        return DemandForecast(p10=p50 - lower_spread, p50=p50, p90=p50 + upper_spread)
