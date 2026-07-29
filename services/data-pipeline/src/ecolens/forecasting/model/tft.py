"""Temporal Fusion Transformer (Lim et al. 2019) -- root TODO.md's "Stand up
the TFT: VSN + attention + decoder backbone, with an adaptive head."

A faithful-but-scoped TFT: real gated residual networks (GRN), real
variable selection (VSN, both static and temporal), real static-covariate
encoding (region only -- `network_code` doesn't exist anywhere in this
repo's mart despite `approach.md` naming it), and real interpretable
multi-head self-attention. The one deliberate simplification, inherited
from `model/lstm.py`'s own precedent: this repo has no known-future
covariates (no forecast weather is ingested), so there's nothing for a
full seq2seq decoder to condition on at future timesteps. Output heads
read the *last* encoded timestep via three linear layers producing
`(batch, horizon)` directly -- exactly `DemandLSTM`'s
`head_p50`/`head_p10`/`head_p90` shape -- so `forward()`'s contract stays
compatible with `training/losses.py`, `evaluation/conformal.py`, and
`evaluation/metrics.py` unchanged.

Trained via `service/training/train_tft.py` (a parallel module to
`training/train.py`, not a modification of it -- see that file's
docstring for why) and registered under its own MLflow experiment/
registered-model name (`Settings.mlflow_experiment_name_tft`/
`mlflow_registered_model_name_tft`), independent of the LSTM's.
"""

from __future__ import annotations

import torch
from torch import nn

Hidden = tuple[torch.Tensor, torch.Tensor]


class GatedLinearUnit(nn.Module):
    """`GLU(x) = a * sigmoid(b)` where `[a, b] = Linear(x)` split in half --
    lets every gated block below learn to suppress irrelevant inputs
    entirely (gate -> 0) rather than just attenuate them.
    """

    def __init__(self, input_dim: int, output_dim: int) -> None:
        super().__init__()
        self.output_dim = output_dim
        self.fc = nn.Linear(input_dim, output_dim * 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        projected = self.fc(x)
        a, b = projected[..., : self.output_dim], projected[..., self.output_dim :]
        return a * torch.sigmoid(b)


class GatedResidualNetwork(nn.Module):
    """The TFT paper's core building block:
    `GRN(x, c) = LayerNorm(skip(x) + GLU(W2 * ELU(W1*x + Wc*c + b1) + b2))`.

    `context`, if given, is broadcast onto every position of `x` before
    the nonlinearity (e.g. a `(batch, context_dim)` static context added
    across `x`'s `(batch, lookback, input_dim)` time dimension). `skip` is
    an identity when `input_dim == output_dim`, otherwise a learned linear
    projection so the residual add is shape-valid.
    """

    def __init__(
        self,
        input_dim: int,
        hidden_dim: int,
        output_dim: int,
        dropout: float,
        *,
        context_dim: int | None = None,
    ) -> None:
        super().__init__()
        self.fc1 = nn.Linear(input_dim, hidden_dim)
        self.context_fc = (
            nn.Linear(context_dim, hidden_dim, bias=False) if context_dim else None
        )
        self.elu = nn.ELU()
        self.fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.dropout = nn.Dropout(dropout)
        self.glu = GatedLinearUnit(hidden_dim, output_dim)
        self.skip = (
            nn.Identity()
            if input_dim == output_dim
            else nn.Linear(input_dim, output_dim)
        )
        self.layer_norm = nn.LayerNorm(output_dim)

    def forward(
        self, x: torch.Tensor, context: torch.Tensor | None = None
    ) -> torch.Tensor:
        a = self.fc1(x)
        if context is not None and self.context_fc is not None:
            c = self.context_fc(context)
            if c.dim() == a.dim() - 1:
                c = c.unsqueeze(-2)  # broadcast a (batch, dim) context over time
            a = a + c
        a = self.elu(a)
        a = self.dropout(self.fc2(a))
        gated = self.glu(a)
        return self.layer_norm(self.skip(x) + gated)


class GateAddNorm(nn.Module):
    """The paper's other recurring gated-skip pattern (used around the
    LSTM encoder and around attention): `LayerNorm(skip + GLU(x))`, no
    feature-mixing MLP -- lighter than a full GRN, used where the two
    inputs are already the same representation, just at different
    processing stages.
    """

    def __init__(self, dim: int, dropout: float) -> None:
        super().__init__()
        self.dropout = nn.Dropout(dropout)
        self.glu = GatedLinearUnit(dim, dim)
        self.layer_norm = nn.LayerNorm(dim)

    def forward(self, x: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        return self.layer_norm(skip + self.glu(self.dropout(x)))


class VariableSelectionNetwork(nn.Module):
    """Learns, per timestep, how much weight each of `num_vars` scalar
    covariates deserves -- real selection (a softmax over feature-specific
    GRN-transformed embeddings), not a fixed/uniform combination.
    `context`, if given (the static `c_selection` vector below), lets the
    selection weights vary by region.

    Inspectable later for root TODO.md's Feature Selection "Step 5" (TFT
    VSN-weight-driven pruning) via the second element this returns -- not
    wired up to that step yet, out of scope here.
    """

    def __init__(
        self,
        num_vars: int,
        d_model: int,
        dropout: float,
        *,
        context_dim: int | None = None,
    ) -> None:
        super().__init__()
        self.num_vars = num_vars
        self.var_embeddings = nn.ModuleList(
            [nn.Linear(1, d_model) for _ in range(num_vars)]
        )
        self.var_grns = nn.ModuleList(
            [
                GatedResidualNetwork(d_model, d_model, d_model, dropout)
                for _ in range(num_vars)
            ]
        )
        self.selection_grn = GatedResidualNetwork(
            num_vars * d_model, d_model, num_vars, dropout, context_dim=context_dim
        )

    def forward(
        self, x: torch.Tensor, context: torch.Tensor | None = None
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """`x`: `(batch, lookback, num_vars)`. Returns
        `(combined (batch, lookback, d_model), weights (batch, lookback, num_vars))`.
        """
        per_var = [
            self.var_embeddings[i](x[..., i : i + 1]) for i in range(self.num_vars)
        ]
        embeds = torch.stack(per_var, dim=-2)  # (batch, lookback, num_vars, d_model)
        flat = embeds.reshape(
            *embeds.shape[:-2], -1
        )  # (batch, lookback, num_vars*d_model)

        logits = self.selection_grn(flat, context)  # (batch, lookback, num_vars)
        weights = torch.softmax(logits, dim=-1)

        transformed = torch.stack(
            [self.var_grns[i](embeds[..., i, :]) for i in range(self.num_vars)], dim=-2
        )  # (batch, lookback, num_vars, d_model)
        combined = (weights.unsqueeze(-1) * transformed).sum(dim=-2)
        return combined, weights


class DemandTFT(nn.Module):
    def __init__(
        self,
        *,
        n_features: int,
        d_model: int,
        num_heads: int,
        num_lstm_layers: int,
        num_regions: int,
        static_dim: int,
        horizon: int,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.n_features = n_features
        self.d_model = d_model
        self.num_heads = num_heads
        self.num_lstm_layers = num_lstm_layers
        self.num_regions = num_regions
        self.static_dim = static_dim
        self.horizon = horizon
        self.dropout = dropout

        # Static covariate encoder: region -> three separate context
        # vectors, one per point the paper injects static information
        # (selection, initial recurrent state, post-encoder enrichment).
        self.region_embedding = nn.Embedding(num_regions, static_dim)
        self.static_grn_selection = GatedResidualNetwork(
            static_dim, static_dim, d_model, dropout
        )
        self.static_grn_state = GatedResidualNetwork(
            static_dim, static_dim, d_model * 2, dropout
        )
        self.static_grn_enrichment = GatedResidualNetwork(
            static_dim, static_dim, d_model, dropout
        )

        self.temporal_vsn = VariableSelectionNetwork(
            n_features, d_model, dropout, context_dim=d_model
        )

        self.lstm = nn.LSTM(
            input_size=d_model,
            hidden_size=d_model,
            num_layers=num_lstm_layers,
            batch_first=True,
        )
        self.lstm_gate = GateAddNorm(d_model, dropout)

        self.static_enrichment_grn = GatedResidualNetwork(
            d_model, d_model, d_model, dropout, context_dim=d_model
        )

        self.attention = nn.MultiheadAttention(
            d_model, num_heads, dropout=dropout, batch_first=True
        )
        self.attention_gate = GateAddNorm(d_model, dropout)

        self.position_wise_grn = GatedResidualNetwork(
            d_model, d_model, d_model, dropout
        )
        self.final_gate = GateAddNorm(d_model, dropout)

        self.head_p50 = nn.Linear(d_model, horizon)
        self.head_p10 = nn.Linear(d_model, horizon)
        self.head_p90 = nn.Linear(d_model, horizon)

    def forward(
        self,
        x: torch.Tensor,
        region_idx: torch.Tensor,
        hidden: Hidden | None = None,
    ) -> tuple[dict[str, torch.Tensor], Hidden]:
        """`x`: `(batch, lookback, n_features)`. `region_idx`: `(batch,)`
        LongTensor, the static categorical covariate. `hidden`, if given,
        overrides the static-derived initial LSTM state -- unused by
        training (each window is an independent example, same as
        `DemandLSTM`), but the seam exists for interface parity should a
        future streaming/incremental path want it.
        """
        static_emb = self.region_embedding(region_idx)  # (batch, static_dim)
        c_selection = self.static_grn_selection(static_emb)  # (batch, d_model)
        c_enrichment = self.static_grn_enrichment(static_emb)  # (batch, d_model)

        if hidden is None:
            state = self.static_grn_state(static_emb)  # (batch, 2*d_model)
            h0, c0 = state[..., : self.d_model], state[..., self.d_model :]
            h0 = h0.unsqueeze(0).expand(self.num_lstm_layers, -1, -1).contiguous()
            c0 = c0.unsqueeze(0).expand(self.num_lstm_layers, -1, -1).contiguous()
            hidden = (h0, c0)

        vsn_out, _selection_weights = self.temporal_vsn(x, context=c_selection)

        enc_out, new_hidden = self.lstm(vsn_out, hidden)
        enriched_in = self.lstm_gate(enc_out, vsn_out)
        enriched = self.static_enrichment_grn(enriched_in, context=c_enrichment)

        attn_out, _attn_weights = self.attention(enriched, enriched, enriched)
        attn_gated = self.attention_gate(attn_out, enriched)

        ff_out = self.position_wise_grn(attn_gated)
        final = self.final_gate(ff_out, attn_gated)

        last_step = final[:, -1, :]  # (batch, d_model) -- final timestep
        predictions = {
            "p50": self.head_p50(last_step),
            "p10": self.head_p10(last_step),
            "p90": self.head_p90(last_step),
        }
        return predictions, new_hidden

    def variable_selection_weights(
        self, x: torch.Tensor, region_idx: torch.Tensor
    ) -> torch.Tensor:
        """Root TODO.md's Feature Selection "Step 5 — TFT variable-selection
        gating": exposes the temporal VSN's per-feature selection weights
        `forward()` itself computes and discards (`_selection_weights` at
        the point `vsn_out` is built above), without re-running the rest
        of the network. Recomputes only the static-selection-context path
        `forward()` also runs (`region_embedding` → `static_grn_selection`)
        since the VSN's weights are conditioned on it.

        Returns `(batch, lookback, n_features)`, softmax weights over the
        last dim — see `service/feature_selection.py`'s `step5_tft_vsn_gating`
        for how these get aggregated into a keep/drop decision.
        """
        static_emb = self.region_embedding(region_idx)
        c_selection = self.static_grn_selection(static_emb)
        _combined, weights = self.temporal_vsn(x, context=c_selection)
        return weights

    def architecture_dict(self) -> dict[str, int | float]:
        """Mirrors `DemandLSTM.architecture_dict()` -- the constructor
        kwargs needed to reconstruct an empty instance of this exact shape
        for `state_dict` loading (see `mlops/registry.py`).
        """
        return {
            "n_features": self.n_features,
            "d_model": self.d_model,
            "num_heads": self.num_heads,
            "num_lstm_layers": self.num_lstm_layers,
            "num_regions": self.num_regions,
            "static_dim": self.static_dim,
            "horizon": self.horizon,
            "dropout": self.dropout,
        }


__all__ = [
    "DemandTFT",
    "GatedLinearUnit",
    "GatedResidualNetwork",
    "GateAddNorm",
    "VariableSelectionNetwork",
    "Hidden",
]
