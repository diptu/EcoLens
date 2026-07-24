"""ECO-111: The LSTM Model.

A plain `nn.Module` (root `TODO.md`'s ECO-111 left PyTorch Lightning as
an open question, not an assumption; skipped here for the same reason
this repo already picked `mlflow-skinny` over full `mlflow` and cron+CLI
over Prefect elsewhere -- the lighter dependency until something
concrete demands the heavier one).

Multivariate, multi-horizon: a stacked `nn.LSTM` consumes the last
`lookback` timesteps of `forecasting/features.py`'s feature vector, and
three linear heads read off the final hidden state to produce
`horizon` steps each of a point forecast (P50) and two raw quantile
forecasts (P10/P90) trained via `training/losses.py`'s pinball loss.
The P10/P90 heads are *raw* model output, not calibrated intervals --
`evaluation/conformal.py` (ECO-114) turns them into statistically
covered bands on a held-out calibration split; this module only has to
produce something in the right shape for that step to calibrate.
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
            # nn.LSTM's own `dropout` kwarg only applies *between* stacked
            # layers -- passing it with num_layers=1 is a no-op PyTorch
            # warns about, so it's only wired up when there's more than
            # one layer to apply it between.
            dropout=dropout if num_layers > 1 else 0.0,
        )
        self.head_p50 = nn.Linear(hidden_size, horizon)
        self.head_p10 = nn.Linear(hidden_size, horizon)
        self.head_p90 = nn.Linear(hidden_size, horizon)

    def forward(
        self, x: torch.Tensor, hidden: Hidden | None = None
    ) -> tuple[dict[str, torch.Tensor], Hidden]:
        """`x`: `(batch, lookback, n_features)`.

        Accepts/returns the LSTM's hidden state so a caller doing
        successive incremental forecasts (strategy.md §6, "Handling
        Hidden States") can carry context forward between calls
        instead of always starting from a zeroed state -- training
        here always passes `hidden=None` (each window is an
        independent supervised example), but the seam exists for
        `training/online.py` and forecast-api's future streaming path.
        """
        out, new_hidden = self.lstm(x, hidden)
        last_step = out[:, -1, :]  # (batch, hidden_size) -- final timestep
        predictions = {
            "p50": self.head_p50(last_step),
            "p10": self.head_p10(last_step),
            "p90": self.head_p90(last_step),
        }
        return predictions, new_hidden

    def architecture_dict(self) -> dict[str, int | float]:
        """The constructor kwargs needed to build an empty instance of this
        exact shape -- logged alongside the `state_dict` (see
        `mlops/registry.py`'s `log_model_artifacts`) so a *different*
        service (`forecast-api`, which deliberately does not depend on
        this package -- see that service's `forecasting/model.py`) can
        reconstruct the architecture and load weights into it without
        ever needing this class to be importable there.
        """
        return {
            "n_features": self.n_features,
            "hidden_size": self.hidden_size,
            "num_layers": self.num_layers,
            "horizon": self.horizon,
            "dropout": self.dropout,
        }


__all__ = ["DemandLSTM", "Hidden"]
