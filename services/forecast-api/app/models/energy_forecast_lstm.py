from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn.functional as F
from torch import Tensor, nn

# Quantile index constants for `EnergyForecast`'s trailing `[..., 3]` dim.
P10 = 0
P50 = 1
P90 = 2


@dataclass
class EnergyForecast:
    """One forward pass's output.

    demand:
        `(batch, horizon, 3)` -- last dim indexed by `P10`/`P50`/`P90`.
    generation:
        `(batch, horizon, sources, 3)` -- same quantile indexing, one
        row per generation-mix bucket (`GENERATION_SOURCES` order:
        coal/gas/wind/solar/other -- `TODO.md`'s Phase B note on why 5
        buckets, not the full `dim_energy_mix` taxonomy).
    """

    demand: Tensor
    generation: Tensor


class MonotonicQuantileHead(nn.Module):
    """Produces ordered, non-negative `[P10, P50, P90]` from a hidden
    state -- guarantees `0 <= P10 <= P50 <= P90`, avoiding quantile
    crossing during inference without a post-hoc sort."""

    def __init__(self, hidden_size: int) -> None:
        super().__init__()
        self.base = nn.Linear(hidden_size, 1)
        self.delta_p50 = nn.Linear(hidden_size, 1)
        self.delta_p90 = nn.Linear(hidden_size, 1)

    def forward(self, x: Tensor) -> Tensor:
        p10 = F.softplus(self.base(x))
        p50 = p10 + F.softplus(self.delta_p50(x))
        p90 = p50 + F.softplus(self.delta_p90(x))
        return torch.cat([p10, p50, p90], dim=-1)


class GenerationQuantileHead(nn.Module):
    """Same monotonic-quantile guarantee as `MonotonicQuantileHead`, but
    per generation-mix source simultaneously.

    Output: `(batch, horizon, sources, 3)`, `0 <= P10 <= P50 <= P90` for
    every source independently.
    """

    def __init__(self, hidden_size: int, n_sources: int) -> None:
        super().__init__()
        self.n_sources = n_sources
        self.base = nn.Linear(hidden_size, n_sources)
        self.delta_p50 = nn.Linear(hidden_size, n_sources)
        self.delta_p90 = nn.Linear(hidden_size, n_sources)

    def forward(self, x: Tensor) -> Tensor:
        p10 = F.softplus(self.base(x))
        p50 = p10 + F.softplus(self.delta_p50(x))
        p90 = p50 + F.softplus(self.delta_p90(x))
        # [B, H, S] -> [B, H, S, 3]
        return torch.stack([p10, p50, p90], dim=-1)


class EnergyForecastLSTM(nn.Module):
    """Multi-output, multi-horizon, probabilistic LSTM: total demand +
    generation-mix-by-source, both as `P10`/`P50`/`P90`.

    Input: `x`, `(batch, history_length, input_features)` -- e.g.
    `(32, 336, len(FEATURE_COLUMNS))` for 7 days of 30-minute lookback.

    Output: `EnergyForecast(demand=(batch, horizon, 3),
    generation=(batch, horizon, sources, 3))`.

    Direct multi-horizon decoding (see module docstring's point 1) -- the
    decoder does not recursively consume its own previous predictions;
    each future step is generated from the historical context combined
    with a learned horizon-position embedding.
    """

    def __init__(
        self,
        input_features: int,
        hidden_size: int = 128,
        num_layers: int = 2,
        horizon: int = 48,
        dropout: float = 0.2,
        generation_sources: int = 5,
    ) -> None:
        super().__init__()
        self.input_features = input_features
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.horizon = horizon
        self.dropout_rate = dropout
        self.generation_sources = generation_sources

        self.input_projection = nn.Sequential(
            nn.Linear(input_features, hidden_size),
            nn.LayerNorm(hidden_size),
            nn.GELU(),
        )

        self.encoder = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=(dropout if num_layers > 1 else 0.0),
        )

        # One learned embedding per forecast step (e.g. embedding[0] ->
        # +30min, embedding[47] -> +24h for horizon=48).
        self.horizon_embedding = nn.Parameter(torch.randn(1, horizon, hidden_size))

        self.decoder = nn.LSTM(
            input_size=hidden_size,
            hidden_size=hidden_size,
            num_layers=1,
            batch_first=True,
        )

        self.dropout = nn.Dropout(dropout)

        self.demand_head = MonotonicQuantileHead(hidden_size=hidden_size)
        self.generation_head = GenerationQuantileHead(
            hidden_size=hidden_size,
            n_sources=generation_sources,
        )

    def encode(self, x: Tensor) -> Tensor:
        """`x`: `(B, T, F)` -> historical context `(B, H)` (the encoder
        LSTM's final-timestep hidden state)."""
        x = self.input_projection(x)
        encoded, _ = self.encoder(x)
        return encoded[:, -1, :]

    def forward(self, x: Tensor) -> EnergyForecast:
        batch_size = x.size(0)

        context = self.encode(x).unsqueeze(1)  # [B, 1, H]
        horizon_embedding = self.horizon_embedding.expand(batch_size, -1, -1)

        # Every future step receives historical context + its own
        # horizon position.
        decoder_input = context + horizon_embedding  # [B, horizon, H]
        decoded, _ = self.decoder(decoder_input)
        decoded = self.dropout(decoded)

        demand = self.demand_head(decoded)
        generation = self.generation_head(decoded)

        return EnergyForecast(demand=demand, generation=generation)
