"""ECO-F03: the LSTM architecture, mirrored from `data-pipeline`.

This is a deliberate, structural duplicate of
`data-pipeline/src/ecolens/forecasting/models/lstm.py`'s `DemandLSTM` --
**not** an import of it. `forecast-api` never depends on `data-pipeline`
as a package (that would pull in `torch`'s training-side neighbors --
`dbt-core`, `pandas`, `optuna`, `scipy`, `motor`, `pymongo` -- into a
service that only ever loads a `state_dict` and runs inference; see
`strategy.md` §2's service boundary). A `state_dict` has no class
identity baked in -- any `nn.Module` with matching layer names/shapes
can load one -- so this file only needs to be *structurally* identical
to the training-side class, not the same Python object.

If you change layer shapes/names in `data-pipeline`'s `DemandLSTM`,
change this file to match, or `load_state_dict` will fail loudly (a
missing/unexpected-key error, not silent corruption) the next time this
service reloads a model trained after the change -- see
`test_forecasting_loader.py` for a round-trip test that would catch a
drift between the two.
"""

from __future__ import annotations

import torch
from torch import nn

Hidden = tuple[torch.Tensor, torch.Tensor]


class DemandLSTM(nn.Module):
    def __init__(
        self,
        *,
        n_features: int,
        hidden_size: int,
        num_layers: int,
        horizon: int,
        dropout: float = 0.2,
    ) -> None:
        super().__init__()
        self.n_features = n_features
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.horizon = horizon
        self.dropout = dropout

        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.head_p50 = nn.Linear(hidden_size, horizon)
        self.head_p10 = nn.Linear(hidden_size, horizon)
        self.head_p90 = nn.Linear(hidden_size, horizon)

    def forward(
        self, x: torch.Tensor, hidden: Hidden | None = None
    ) -> tuple[dict[str, torch.Tensor], Hidden]:
        """`x`: `(batch, lookback, n_features)`."""
        out, new_hidden = self.lstm(x, hidden)
        last_step = out[:, -1, :]
        predictions = {
            "p50": self.head_p50(last_step),
            "p10": self.head_p10(last_step),
            "p90": self.head_p90(last_step),
        }
        return predictions, new_hidden


__all__ = ["DemandLSTM", "Hidden"]
