from __future__ import annotations

import torch

from app.models.ml import DemandLSTM


def test_forward_pass_produces_correct_shapes():
    model = DemandLSTM(n_features=10, horizon=48, hidden_size=16, num_layers=2)
    x = torch.randn(4, 24, 10)  # (batch, lookback, n_features)

    out = model(x)

    assert out.p10.shape == (4, 48)
    assert out.p50.shape == (4, 48)
    assert out.p90.shape == (4, 48)


def test_quantiles_never_cross_at_init():
    """p10 <= p50 <= p90 must hold by construction, even before any
    training -- the softplus-spread parameterisation is what guarantees
    this (see `model.py`'s module docstring)."""
    model = DemandLSTM(n_features=6, horizon=12, hidden_size=8, num_layers=1)
    x = torch.randn(32, 16, 6)

    out = model(x)

    assert torch.all(out.p10 <= out.p50 + 1e-6)
    assert torch.all(out.p50 <= out.p90 + 1e-6)


def test_single_layer_lstm_does_not_error_on_dropout():
    # nn.LSTM warns (doesn't error) about dropout with num_layers=1; this
    # just documents/guards that a 1-layer model still builds and runs.
    model = DemandLSTM(
        n_features=3, horizon=4, hidden_size=8, num_layers=1, dropout=0.2
    )
    x = torch.randn(2, 8, 3)

    out = model(x)

    assert out.p50.shape == (2, 4)


def test_gradients_flow_to_all_three_heads():
    model = DemandLSTM(n_features=5, horizon=6, hidden_size=8, num_layers=2)
    x = torch.randn(3, 10, 5)

    out = model(x)
    loss = out.p10.sum() + out.p50.sum() + out.p90.sum()
    loss.backward()

    assert model.point_head.weight.grad is not None
    assert model.lower_spread_head.weight.grad is not None
    assert model.upper_spread_head.weight.grad is not None
    assert model.lstm.weight_ih_l0.grad is not None
