"""Tests for ecolens.forecasting.model.timesfm_head (root TODO.md "Stand
up TimesFM"). No dependency on the real `timesfm` package at all -- this
head never touches TimesFM, only its already-computed output (fed in as
plain tensors here), so these run exactly as fast as the LSTM/TFT model
tests.
"""

from __future__ import annotations

import torch

from ecolens.forecasting.model.timesfm_head import TimesFMCalibrationHead


def _head(**overrides) -> TimesFMCalibrationHead:
    kwargs = dict(horizon=48, num_regions=3, static_dim=8, hidden_dim=16, dropout=0.0)
    kwargs.update(overrides)
    return TimesFMCalibrationHead(**kwargs)


def _raw(
    batch: int = 4, horizon: int = 48
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    p50 = torch.randn(batch, horizon)
    return p50 - 0.5, p50, p50 + 0.5


class TestTimesFMCalibrationHead:
    def test_output_shapes(self):
        head = _head()
        raw_p10, raw_p50, raw_p90 = _raw()
        region_idx = torch.randint(0, 3, (4,))
        outputs = head(raw_p10, raw_p50, raw_p90, region_idx)
        assert set(outputs) == {"p50", "p10", "p90"}
        for value in outputs.values():
            assert value.shape == (4, 48)

    def test_gradients_flow_to_all_parameters(self):
        head = _head()
        raw_p10, raw_p50, raw_p90 = _raw()
        region_idx = torch.randint(0, 3, (4,))
        outputs = head(raw_p10, raw_p50, raw_p90, region_idx)
        loss = outputs["p50"].sum() + outputs["p10"].sum() + outputs["p90"].sum()
        loss.backward()
        for name, param in head.named_parameters():
            assert param.grad is not None, f"{name} got no gradient"
            assert torch.isfinite(param.grad).all(), f"{name} got a non-finite gradient"

    def test_different_regions_produce_different_output(self):
        # Region is the only static covariate this head sees -- proves it
        # actually reaches the output, same check test_forecasting_tft.py
        # runs for DemandTFT's static encoder.
        head = _head()
        head.eval()
        raw_p10, raw_p50, raw_p90 = _raw(batch=2)
        region_a = torch.zeros(2, dtype=torch.long)
        region_b = torch.full((2,), 2, dtype=torch.long)
        with torch.no_grad():
            out_a = head(raw_p10, raw_p50, raw_p90, region_a)
            out_b = head(raw_p10, raw_p50, raw_p90, region_b)
        assert not torch.allclose(out_a["p50"], out_b["p50"])

    def test_is_an_additive_correction_not_a_from_scratch_predictor(self):
        # Operates in this repo's scaled space (roughly unit magnitude --
        # see the module docstring), so "close to raw" has to be checked
        # at that scale, not raw MW. A wildly different raw_p50 should
        # still move the output roughly in step with it -- proof the
        # raw forecast is actually flowing through as a base value the
        # head corrects, not something the correction heads ignore.
        head = _head()
        head.eval()
        region_idx = torch.zeros(2, dtype=torch.long)
        low = torch.full((2, 48), -2.0)
        high = torch.full((2, 48), 2.0)
        with torch.no_grad():
            out_low = head(low - 0.5, low, low + 0.5, region_idx)
            out_high = head(high - 0.5, high, high + 0.5, region_idx)
        assert (out_high["p50"] - out_low["p50"]).mean().item() > 1.0

    def test_architecture_dict_round_trip(self):
        head = _head()
        arch = head.architecture_dict()
        rebuilt = TimesFMCalibrationHead(**arch)
        rebuilt.load_state_dict(head.state_dict())

        raw_p10, raw_p50, raw_p90 = _raw(batch=3)
        region_idx = torch.randint(0, 3, (3,))
        head.eval()
        rebuilt.eval()
        with torch.no_grad():
            out_orig = head(raw_p10, raw_p50, raw_p90, region_idx)
            out_rebuilt = rebuilt(raw_p10, raw_p50, raw_p90, region_idx)
        assert torch.allclose(out_orig["p50"], out_rebuilt["p50"])
