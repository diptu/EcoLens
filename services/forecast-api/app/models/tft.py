"""`DemandTFT` — a hand-rolled Temporal Fusion Transformer
(`todo-model-training.md` Phase 2; Lim et al. 2019, "Temporal Fusion
Transformers for Interpretable Multi-horizon Time Series Forecasting").

**Decision recorded** (Phase 2's own explicit decision point): hand-rolled,
not adopted from `pytorch-forecasting`. That library's
`TemporalFusionTransformer` hard-requires `lightning` (PyTorch Lightning)
as a real, unavoidable dependency (`pytorch-forecasting`'s own published
`requires_dist`, checked directly at implementation time) — `ml/train.py`'s
own docstring already deliberately rejected Lightning for `DemandLSTM`
("Lightning's abstraction isn't pulling its weight as a new dependency").
Adopting `pytorch-forecasting` here would silently reintroduce exactly the
dependency this repo already decided against, for a second model, without
revisiting that decision. This is the "specific reason (dependency
weight...)" this phase's own decision point names as real grounds to
hand-roll instead — matches `DemandLSTM`'s own from-scratch style in this
same module directory (`app/models/ml.py`).

**Per-region, not multi-region** (Phase 2's other explicit decision point):
trained one-model-per-region, mirroring `DemandLSTM`'s existing convention
exactly (lower risk, consistent with how every other model in this repo is
trained/evaluated/registered) rather than one joint multi-region model
with `region` as a static covariate. A real, direct consequence: this v0
TFT has no static covariates at all — there's nothing series-varying left
to encode once `region` is fixed per model instance. The static-enrichment
layer stays in the architecture below (real, paper-faithful shape) so a
future multi-region TFT can wire real static inputs in without
restructuring this module, but `static_context` is always a zero vector
today — a documented no-op, not silently implied as already useful.

Architecture (Lim et al. 2019, faithful but intentionally minimal — no
quantile-loss-specific attention regularisation, no multi-quantile output
beyond this project's existing P10/P50/P90 convention):

    Variable Selection Network
      (encoder: `OBSERVED_PAST_COLUMNS + KNOWN_FUTURE_COLUMNS`,
       decoder: `KNOWN_FUTURE_COLUMNS` only — see `ml/features.py`)
      -> LSTM encoder (`lookback` steps) / LSTM decoder (`horizon` steps,
         seeded from the encoder's final hidden/cell state)
      -> gated skip connection ("sequence-to-sequence layer", eq. 10-11)
      -> static enrichment (GRN; always a zero context in this v0)
      -> interpretable multi-head self-attention (causal-masked over the
         full encoder+decoder sequence, a *shared* value projection
         across heads — the "interpretable" half of TFT's attention,
         eq. 14-16)
      -> position-wise feed-forward (GRN) + gated residual from the
         pre-attention representation (eq. 17)
      -> three heads (point / lower-spread / upper-spread), the same
         `point -/+ softplus(delta)` parameterisation `DemandLSTM` uses,
         for exact `DemandForecast` contract parity — see that module's
         docstring for why this structurally guarantees `p10<=p50<=p90`.
"""

from __future__ import annotations

import torch
import torch.nn.functional as F
from torch import Tensor, nn

from app.models.ml import DemandForecast


class GLU(nn.Module):
    """Gated Linear Unit: a linear projection to `2 * output_size`, split
    in half, one half sigmoid-gates the other. TFT's universal gating
    mechanism — every skip connection in this module passes through one,
    letting the network learn to suppress a whole sub-block's contribution
    (gate -> 0) when it isn't useful for a given input, rather than always
    adding its full output."""

    def __init__(self, input_size: int, output_size: int | None = None) -> None:
        super().__init__()
        output_size = output_size or input_size
        self.fc = nn.Linear(input_size, output_size * 2)

    def forward(self, x: Tensor) -> Tensor:
        a, b = self.fc(x).chunk(2, dim=-1)
        return a * torch.sigmoid(b)


class GatedResidualNetwork(nn.Module):
    """GRN: TFT's core building block (eq. 2-4). ELU-activated 2-layer
    MLP, gated (`GLU`) skip connection back to a (possibly linearly
    projected, if `input_size != output_size`) residual, then
    `LayerNorm`. Optionally incorporates a separate `context` vector
    (e.g. static enrichment) via an additive projection before the
    nonlinearity."""

    def __init__(
        self,
        input_size: int,
        hidden_size: int,
        output_size: int | None = None,
        context_size: int | None = None,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        output_size = output_size or input_size
        self.skip = (
            nn.Linear(input_size, output_size)
            if input_size != output_size
            else nn.Identity()
        )
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.context_proj = (
            nn.Linear(context_size, hidden_size, bias=False) if context_size else None
        )
        self.fc2 = nn.Linear(hidden_size, hidden_size)
        self.dropout = nn.Dropout(dropout)
        self.glu = GLU(hidden_size, output_size)
        self.layer_norm = nn.LayerNorm(output_size)

    def forward(self, x: Tensor, context: Tensor | None = None) -> Tensor:
        residual = self.skip(x)
        hidden = self.fc1(x)
        if context is not None and self.context_proj is not None:
            hidden = hidden + self.context_proj(context)
        hidden = self.fc2(F.elu(hidden))
        gated = self.glu(self.dropout(hidden))
        return self.layer_norm(residual + gated)


class VariableSelectionNetwork(nn.Module):
    """Instance-wise variable selection (eq. 6-8): each scalar input
    variable is projected to `hidden_size` and passed through its own
    `GatedResidualNetwork` independently, then combined via a
    softmax-weighted sum — the weights themselves produced by a `GRN`
    over the flattened (projected, pre-per-variable-GRN) input vector, so
    the model learns *per timestep* which of its input variables actually
    matter right now, rather than treating every input as equally
    relevant at every step."""

    def __init__(
        self,
        n_vars: int,
        hidden_size: int,
        context_size: int | None = None,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.n_vars = n_vars
        self.var_projections = nn.ModuleList(
            [nn.Linear(1, hidden_size) for _ in range(n_vars)]
        )
        self.var_grns = nn.ModuleList(
            [
                GatedResidualNetwork(hidden_size, hidden_size, dropout=dropout)
                for _ in range(n_vars)
            ]
        )
        self.weight_grn = GatedResidualNetwork(
            n_vars * hidden_size,
            hidden_size,
            output_size=n_vars,
            context_size=context_size,
            dropout=dropout,
        )

    def forward(
        self, x: Tensor, context: Tensor | None = None
    ) -> tuple[Tensor, Tensor]:
        """`x`: `(..., n_vars)`. Returns `(selected, weights)` —
        `selected` shape `(..., hidden_size)`, `weights` shape
        `(..., n_vars)` (real per-timestep selection weights, useful for
        interpretability even though nothing in this codebase consumes
        them yet)."""
        projected = [
            self.var_projections[i](x[..., i : i + 1]) for i in range(self.n_vars)
        ]
        flat = torch.cat(projected, dim=-1)
        weights = torch.softmax(self.weight_grn(flat, context), dim=-1)
        transformed = torch.stack(
            [grn(p) for grn, p in zip(self.var_grns, projected, strict=True)], dim=-2
        )
        selected = (transformed * weights.unsqueeze(-1)).sum(dim=-2)
        return selected, weights


class InterpretableMultiHeadAttention(nn.Module):
    """TFT's attention variant (eq. 14-16): standard per-head Q/K
    projections, but a *single value projection shared across every
    head* (rather than each head having its own independent V), and head
    outputs are averaged rather than concatenated — since every head
    already shares the same value space, averaging (not concatenating)
    is what makes the resulting per-head attention weights directly
    comparable/interpretable as "how much did each head attend to each
    position", the property that gives this variant its name."""

    def __init__(self, d_model: int, n_heads: int, dropout: float = 0.1) -> None:
        super().__init__()
        if d_model % n_heads != 0:
            raise ValueError(
                f"d_model={d_model} must be divisible by n_heads={n_heads}"
            )
        self.n_heads = n_heads
        self.d_head = d_model // n_heads
        self.q_layers = nn.ModuleList(
            [nn.Linear(d_model, self.d_head, bias=False) for _ in range(n_heads)]
        )
        self.k_layers = nn.ModuleList(
            [nn.Linear(d_model, self.d_head, bias=False) for _ in range(n_heads)]
        )
        self.v_layer = nn.Linear(d_model, self.d_head, bias=False)
        self.out_proj = nn.Linear(self.d_head, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x: Tensor, mask: Tensor | None = None) -> tuple[Tensor, Tensor]:
        """`x`: `(batch, seq, d_model)`. `mask`: `(seq, seq)` bool, `True`
        where attention should be blocked (e.g. a causal upper-triangular
        mask). Returns `(output, attn_weights)` — `attn_weights` averaged
        across heads, shape `(batch, seq, seq)`."""
        v = self.v_layer(x)
        scale = self.d_head**0.5
        head_outputs = []
        head_weights = []
        for q_lin, k_lin in zip(self.q_layers, self.k_layers, strict=True):
            scores = torch.matmul(q_lin(x), k_lin(x).transpose(-2, -1)) / scale
            if mask is not None:
                scores = scores.masked_fill(mask, float("-inf"))
            weights = self.dropout(torch.softmax(scores, dim=-1))
            head_outputs.append(torch.matmul(weights, v))
            head_weights.append(weights)
        combined = torch.stack(head_outputs, dim=0).mean(dim=0)
        avg_weights = torch.stack(head_weights, dim=0).mean(dim=0)
        return self.out_proj(combined), avg_weights


class DemandTFT(nn.Module):
    def __init__(
        self,
        n_encoder_features: int,
        n_decoder_features: int,
        horizon: int,
        hidden_size: int = 64,
        n_heads: int = 4,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.horizon = horizon
        self.hidden_size = hidden_size

        self.encoder_vsn = VariableSelectionNetwork(
            n_encoder_features, hidden_size, dropout=dropout
        )
        self.decoder_vsn = VariableSelectionNetwork(
            n_decoder_features, hidden_size, dropout=dropout
        )
        self.encoder_lstm = nn.LSTM(hidden_size, hidden_size, batch_first=True)
        self.decoder_lstm = nn.LSTM(hidden_size, hidden_size, batch_first=True)
        self.post_lstm_gate = GLU(hidden_size)
        self.post_lstm_norm = nn.LayerNorm(hidden_size)

        # Static enrichment -- real, paper-faithful shape; always fed a
        # zero context in this per-region v0 (see module docstring).
        self.static_enrichment = GatedResidualNetwork(
            hidden_size, hidden_size, dropout=dropout
        )

        self.attention = InterpretableMultiHeadAttention(
            hidden_size, n_heads, dropout=dropout
        )
        self.post_attn_gate = GLU(hidden_size)
        self.post_attn_norm = nn.LayerNorm(hidden_size)

        self.positionwise_grn = GatedResidualNetwork(
            hidden_size, hidden_size, dropout=dropout
        )
        self.final_gate = GLU(hidden_size)
        self.final_norm = nn.LayerNorm(hidden_size)

        self.point_head = nn.Linear(hidden_size, 1)
        self.lower_spread_head = nn.Linear(hidden_size, 1)
        self.upper_spread_head = nn.Linear(hidden_size, 1)

    def forward(self, x_encoder: Tensor, x_decoder: Tensor) -> DemandForecast:
        """`x_encoder`: `(batch, lookback, n_encoder_features)` —
        `OBSERVED_PAST_COLUMNS + KNOWN_FUTURE_COLUMNS` over the lookback
        window. `x_decoder`: `(batch, horizon, n_decoder_features)` —
        `KNOWN_FUTURE_COLUMNS` only, over the forecast horizon (this
        model never sees observed-past-only features for future
        timesteps — they genuinely aren't knowable then). Returns a
        `DemandForecast` of `(batch, horizon)` tensors, same contract as
        `DemandLSTM.forward`.
        """
        _, lookback, _ = x_encoder.shape

        enc_selected, _ = self.encoder_vsn(x_encoder)
        dec_selected, _ = self.decoder_vsn(x_decoder)

        enc_lstm_out, (h_n, c_n) = self.encoder_lstm(enc_selected)
        dec_lstm_out, _ = self.decoder_lstm(dec_selected, (h_n, c_n))

        lstm_out = torch.cat([enc_lstm_out, dec_lstm_out], dim=1)
        vsn_out = torch.cat([enc_selected, dec_selected], dim=1)
        gated_lstm = self.post_lstm_norm(vsn_out + self.post_lstm_gate(lstm_out))

        enriched = self.static_enrichment(gated_lstm)

        seq_len = gated_lstm.shape[1]
        causal_mask = torch.triu(
            torch.ones(seq_len, seq_len, dtype=torch.bool, device=x_encoder.device),
            diagonal=1,
        )
        attn_out, _ = self.attention(enriched, mask=causal_mask)
        gated_attn = self.post_attn_norm(enriched + self.post_attn_gate(attn_out))

        ff_out = self.positionwise_grn(gated_attn)
        # Skip from the pre-attention (`gated_lstm`) representation, not
        # `gated_attn` -- matches the paper's eq. 17 residual source.
        final = self.final_norm(gated_lstm + self.final_gate(ff_out))

        decoder_final = final[:, lookback:, :]
        point = self.point_head(decoder_final).squeeze(-1)
        lower_spread = F.softplus(self.lower_spread_head(decoder_final)).squeeze(-1)
        upper_spread = F.softplus(self.upper_spread_head(decoder_final)).squeeze(-1)

        return DemandForecast(
            p10=point - lower_spread, p50=point, p90=point + upper_spread
        )
