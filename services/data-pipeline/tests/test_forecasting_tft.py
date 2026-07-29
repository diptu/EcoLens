"""Tests for ecolens.forecasting.model.tft (root TODO.md "Stand up the
TFT"). Mirrors test_forecasting_lstm.py's shape/gradient-flow coverage,
plus TFT-specific checks (variable selection weights, static-covariate
sensitivity, architecture_dict round-trip) the LSTM has no equivalent of.
"""

from __future__ import annotations

import torch

from ecolens.forecasting.model.tft import DemandTFT


def _model(**overrides) -> DemandTFT:
    kwargs = dict(
        n_features=23,
        d_model=16,
        num_heads=2,
        num_lstm_layers=1,
        num_regions=3,
        static_dim=8,
        horizon=48,
        dropout=0.0,
    )
    kwargs.update(overrides)
    return DemandTFT(**kwargs)


class TestDemandTFT:
    def test_output_shapes(self):
        model = _model()
        x = torch.randn(4, 48, 23)
        region_idx = torch.randint(0, 3, (4,))
        outputs, hidden = model(x, region_idx)
        assert set(outputs) == {"p50", "p10", "p90"}
        for head in outputs.values():
            assert head.shape == (4, 48)
        h, c = hidden
        assert h.shape == (1, 4, 16)
        assert c.shape == (1, 4, 16)

    def test_multi_layer_with_dropout_does_not_error(self):
        model = _model(num_lstm_layers=2, dropout=0.3)
        x = torch.randn(2, 48, 23)
        region_idx = torch.randint(0, 3, (2,))
        outputs, hidden = model(x, region_idx)
        assert outputs["p50"].shape == (2, 48)
        h, _c = hidden
        assert h.shape == (2, 2, 16)

    def test_gradients_flow_to_all_parameters(self):
        model = _model()
        x = torch.randn(4, 48, 23)
        region_idx = torch.randint(0, 3, (4,))
        outputs, _ = model(x, region_idx)
        loss = outputs["p50"].sum() + outputs["p10"].sum() + outputs["p90"].sum()
        loss.backward()
        for name, param in model.named_parameters():
            assert param.grad is not None, f"{name} got no gradient"
            assert torch.isfinite(param.grad).all(), f"{name} got a non-finite gradient"

    def test_different_regions_produce_different_output(self):
        # The static covariate encoder is the only thing that can vary
        # between these two calls -- same x, same seed-free weights,
        # only region_idx differs. Proves the static context actually
        # reaches the output, not just gets computed and discarded.
        model = _model()
        model.eval()
        x = torch.randn(2, 48, 23)
        region_a = torch.zeros(2, dtype=torch.long)
        region_b = torch.full((2,), 2, dtype=torch.long)
        with torch.no_grad():
            out_a, _ = model(x, region_a)
            out_b, _ = model(x, region_b)
        assert not torch.allclose(out_a["p50"], out_b["p50"])

    def test_architecture_dict_round_trip(self):
        model = _model()
        arch = model.architecture_dict()
        rebuilt = DemandTFT(**arch)
        rebuilt.load_state_dict(model.state_dict())

        x = torch.randn(3, 48, 23)
        region_idx = torch.randint(0, 3, (3,))
        model.eval()
        rebuilt.eval()
        with torch.no_grad():
            out_orig, _ = model(x, region_idx)
            out_rebuilt, _ = rebuilt(x, region_idx)
        assert torch.allclose(out_orig["p50"], out_rebuilt["p50"])


class TestVariableSelectionNetwork:
    def test_temporal_selection_weights_sum_to_one(self):
        from ecolens.forecasting.model.tft import VariableSelectionNetwork

        vsn = VariableSelectionNetwork(
            num_vars=23, d_model=16, dropout=0.0, context_dim=16
        )
        x = torch.randn(4, 48, 23)
        context = torch.randn(4, 16)
        _combined, weights = vsn(x, context=context)
        assert weights.shape == (4, 48, 23)
        assert torch.all(weights >= 0)
        totals = weights.sum(dim=-1)
        assert torch.allclose(totals, torch.ones_like(totals), atol=1e-5)
