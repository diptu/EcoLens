"""Minimal, standalone skeleton of `DemandLSTM` (`app/models/ml.py`),
used only to *generate* an accurate architecture diagram straight from a
real, instantiated `nn.Module`'s own attributes -- not a hand-drawn
image whose numbers can silently drift from the real model.

Why this exists (2026-09-12): a hand-made diagram of `DemandLSTM` went
through three review rounds, each catching a different real-vs-drawn
mismatch -- the dropout value (class default 0.2 vs. the real
`TrainConfig` default of 0.25), the final "Model Output" boxes (drawn as
three independent linear outputs, when the real forward pass applies
softplus to the two spread heads and combines them with the point head
into P10/P50/P90), and a missing `head_dropout` step. A diagram
regenerated from code each time can't drift like that -- there's nothing
to hand-transcribe wrong.

This skeleton is deliberately NOT imported from `app.models.ml`: this
script has zero `app`/DB/MLflow dependencies on purpose (just `torch` +
`matplotlib`), so it can run anywhere without the rest of the service
booting. Its `forward` is byte-for-byte the same shape as the real
`DemandLSTM.forward` (`app/models/ml.py:98-104`) -- same layer order,
same `head_dropout`-before-all-three-heads placement, same
softplus-then-combine construction. If the real class's forward pass
ever changes, this skeleton (and the diagram it draws) needs a matching
update -- the same "kept in sync by hand" cost `app/models/ml.py`'s own
docstring already accepts for its data-pipeline twin.

Usage (from services/forecast-api/):
    uv run python scripts/model_skeleton.py
    # writes model_skeleton.png next to this script
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import torch
from matplotlib.patches import FancyBboxPatch
from torch import Tensor, nn


@dataclass
class DemandForecast:
    """One forward pass's output -- each field shaped `(batch, horizon)`."""

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


class DemandLSTMSkeleton(nn.Module):
    """Structurally identical to `app.models.ml.DemandLSTM` -- see this
    module's own docstring for why it's a separate copy, not an import."""

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
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout

        self.lstm = nn.LSTM(
            input_size=n_features,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            batch_first=True,
        )
        self.attention = AttentionPool(hidden_size)
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


# ---------------------------------------------------------------------------
# Diagram
# ---------------------------------------------------------------------------

_COLORS = {
    "input": ("#fdba74", "#c2410c"),
    "lstm": ("#86efac", "#15803d"),
    "attn": ("#93c5fd", "#1d4ed8"),
    "dropout": ("#fcd34d", "#92400e"),
    "head": ("#a5b4c9", "#334155"),
    "softplus": ("#bae6fd", "#075985"),
    "output": ("#d4d4d8", "#3f3f46"),
}


def _box(ax, cx: float, cy: float, w: float, h: float, text: str, kind: str, fontsize: float = 9.5):
    face, edge = _COLORS[kind]
    ax.add_patch(
        FancyBboxPatch(
            (cx - w / 2, cy - h / 2),
            w,
            h,
            boxstyle="round,pad=0.02,rounding_size=0.15",
            linewidth=1.2,
            edgecolor=edge,
            facecolor=face,
        )
    )
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fontsize, color="#111827", wrap=True)
    return (cx, cy - h / 2), (cx, cy + h / 2)  # (bottom, top) anchor points


def _arrow(ax, p1, p2, label: str | None = None):
    ax.annotate(
        "",
        xy=p2,
        xytext=p1,
        arrowprops=dict(arrowstyle="-|>", color="#374151", lw=1.2, shrinkA=0, shrinkB=0),
    )
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(mx + 0.3, my, label, fontsize=8, color="#374151", va="center")


def draw_architecture(model: DemandLSTMSkeleton, out_path: Path) -> None:
    """Renders `model`'s real, instantiated attributes -- never a
    hardcoded number that could drift from what was actually built."""
    fig, ax = plt.subplots(figsize=(11, 10.5))
    ax.set_xlim(0, 10)
    ax.set_ylim(2.6, 15)
    ax.axis("off")
    ax.set_title(
        f"DemandLSTM — Quantile Regression with Attention (horizon={model.horizon})",
        fontsize=13,
        fontweight="bold",
        pad=14,
    )

    _, input_top = _box(
        ax, 5, 14, 6, 0.9, f"Input Layer\n(n_features={model.n_features} per timestep)", "input"
    )
    lstm_bottom, lstm_top = _box(
        ax,
        5,
        12.4,
        6,
        1.3,
        f"LSTM\nstacked {model.num_layers} layers, {model.hidden_size} hidden units\n"
        f"dropout={model.dropout}, batch_first=True",
        "lstm",
    )
    _arrow(ax, input_top, lstm_top)

    attn_bottom, attn_top = _box(
        ax, 5, 10.7, 6, 0.9, "AttentionPool\n(seq_len, hidden_size) → (hidden_size,)", "attn"
    )
    _arrow(ax, lstm_bottom, attn_top)

    drop_bottom, drop_top = _box(
        ax, 5, 9.4, 6, 0.8, f"Head Dropout (rate={model.dropout})", "dropout"
    )
    _arrow(ax, attn_bottom, drop_top)

    head_y = 8.0
    head_w, head_h = 2.8, 1.3
    point_bottom, point_top = _box(
        ax, 1.8, head_y, head_w, head_h, f"Point Head\nLinear({model.hidden_size} → {model.horizon})", "head"
    )
    lower_bottom, lower_top = _box(
        ax, 5, head_y, head_w, head_h, f"Lower Spread Head\nLinear({model.hidden_size} → {model.horizon})", "head"
    )
    upper_bottom, upper_top = _box(
        ax, 8.2, head_y, head_w, head_h, f"Upper Spread Head\nLinear({model.hidden_size} → {model.horizon})", "head"
    )
    for top in (point_top, lower_top, upper_top):
        _arrow(ax, drop_bottom, top)

    sp_y = 6.4
    lower_sp_bottom, lower_sp_top = _box(ax, 5, sp_y, 2.6, 0.8, "Softplus\n(≥ 0)", "softplus")
    upper_sp_bottom, upper_sp_top = _box(ax, 8.2, sp_y, 2.6, 0.8, "Softplus\n(≥ 0)", "softplus")
    _arrow(ax, lower_bottom, lower_sp_top)
    _arrow(ax, upper_bottom, upper_sp_top)

    out_y = 4.6
    out_w, out_h = 2.8, 1.5
    _, p10_top = _box(
        ax, 1.8, out_y, out_w, out_h, f"P10 Forecast\n({model.horizon} values)\np50 − softplus(lower)", "output"
    )
    _, p50_top = _box(
        ax, 5, out_y, out_w, out_h, f"P50 Forecast\n({model.horizon} values)\npoint_head output", "output"
    )
    _, p90_top = _box(
        ax, 8.2, out_y, out_w, out_h, f"P90 Forecast\n({model.horizon} values)\np50 + softplus(upper)", "output"
    )
    _arrow(ax, point_bottom, p50_top)
    _arrow(ax, point_bottom, p10_top)  # p50 feeds the P10 combination too
    _arrow(ax, point_bottom, p90_top)  # and the P90 combination
    _arrow(ax, lower_sp_bottom, p10_top)
    _arrow(ax, upper_sp_bottom, p90_top)

    ax.text(
        5,
        3.3,
        "P10 ≤ P50 ≤ P90 guaranteed by construction (softplus spreads are\n"
        "structurally non-negative) — not just by training.",
        ha="center",
        va="center",
        fontsize=9,
        color="#374151",
        style="italic",
    )

    fig.tight_layout()
    fig.savefig(out_path, dpi=180)
    plt.close(fig)


def main() -> None:
    # `n_features`/`horizon`/`hidden_size`/`num_layers` match this
    # service's real `Settings.model_demand_lookback`-trained defaults
    # (`app/core/config.py`); `dropout=0.25` is the real `TrainConfig`
    # default (`Settings.model_dropout`), not the class's own bare
    # constructor default of 0.2 -- passed explicitly so the diagram
    # shows what's actually trained, not the unused fallback.
    model = DemandLSTMSkeleton(n_features=37, horizon=48, hidden_size=128, num_layers=2, dropout=0.25)
    out_path = Path(__file__).parent / "model_skeleton.png"
    draw_architecture(model, out_path)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
