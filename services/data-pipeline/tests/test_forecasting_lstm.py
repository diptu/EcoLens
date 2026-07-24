"""Tests for ecolens.forecasting.models.lstm (ECO-111)."""

from __future__ import annotations

import torch

from ecolens.forecasting.models.lstm import DemandLSTM


def _model(**overrides) -> DemandLSTM:
    kwargs = dict(n_features=24, hidden_size=8, num_layers=1, horizon=48, dropout=0.0)
    kwargs.update(overrides)
    return DemandLSTM(**kwargs)


class TestDemandLSTM:
    def test_output_shapes(self):
        model = _model()
        x = torch.randn(4, 48, 24)
        outputs, hidden = model(x)
        assert set(outputs) == {"p50", "p10", "p90"}
        for head in outputs.values():
            assert head.shape == (4, 48)
        h, c = hidden
        assert h.shape == (1, 4, 8)
        assert c.shape == (1, 4, 8)

    def test_multi_layer_with_dropout_does_not_error(self):
        model = _model(num_layers=3, dropout=0.3)
        x = torch.randn(2, 48, 24)
        outputs, _ = model(x)
        assert outputs["p50"].shape == (2, 48)

    def test_hidden_state_can_be_carried_forward(self):
        # A full 48-step sequence can (correctly, for an LSTM) wash out
        # the initial hidden state's influence by the final timestep --
        # that's the model's normal state-decay dynamics, not a bug in
        # the hidden-state plumbing this test is actually checking. Use
        # a single-step sequence instead, where the initial hidden state
        # directly and unavoidably determines the one output, and an
        # extreme (not model-derived) hidden vector so the difference
        # can't vanish by coincidence.
        model = _model()
        x = torch.randn(1, 1, 24)
        extreme_hidden = (torch.full((1, 1, 8), 50.0), torch.full((1, 1, 8), 50.0))

        out_fresh, _ = model(x)
        out_carried, _ = model(x, hidden=extreme_hidden)

        assert not torch.allclose(out_fresh["p50"], out_carried["p50"])

    def test_gradients_flow_to_all_parameters(self):
        model = _model()
        x = torch.randn(4, 48, 24)
        outputs, _ = model(x)
        loss = outputs["p50"].sum() + outputs["p10"].sum() + outputs["p90"].sum()
        loss.backward()
        for name, param in model.named_parameters():
            assert param.grad is not None, f"{name} got no gradient"
            assert torch.isfinite(param.grad).all(), f"{name} got a non-finite gradient"
