"""Tests for ecolens_forecast_api.forecasting.model (ECO-F03)."""

from __future__ import annotations

import torch

from ecolens_forecast_api.forecasting.model import DemandLSTM


class TestDemandLSTM:
    def test_output_shapes(self):
        model = DemandLSTM(n_features=24, hidden_size=8, num_layers=1, horizon=48)
        x = torch.randn(2, 48, 24)
        outputs, hidden = model(x)
        assert set(outputs) == {"p50", "p10", "p90"}
        for head in outputs.values():
            assert head.shape == (2, 48)
        h, c = hidden
        assert h.shape == (1, 2, 8)
        assert c.shape == (1, 2, 8)

    def test_state_dict_keys_match_expected_architecture(self):
        """This is the load-bearing contract with data-pipeline's
        DemandLSTM: if the two ever drift, state_dict loading breaks
        loudly (see loader.py's docstring) -- this test at least locks
        down *this* file's own key set so an accidental local edit is
        caught here too.
        """
        model = DemandLSTM(n_features=24, hidden_size=8, num_layers=2, horizon=48)
        keys = set(model.state_dict().keys())
        expected_prefixes = {"lstm.", "head_p50.", "head_p10.", "head_p90."}
        assert all(any(k.startswith(p) for p in expected_prefixes) for k in keys)
        assert any(k.startswith("lstm.weight_ih_l0") for k in keys)
        assert any(k.startswith("lstm.weight_ih_l1") for k in keys)  # num_layers=2
