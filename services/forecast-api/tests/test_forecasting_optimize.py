"""Tests for ecolens_forecast_api.forecasting.optimize (ECO-F07)."""

from __future__ import annotations

import torch

from ecolens_forecast_api.forecasting.model import DemandLSTM
from ecolens_forecast_api.forecasting.optimize import apply_inference_optimization
from ecolens_forecast_api.settings import ForecastApiSettings


class TestApplyInferenceOptimization:
    def test_none_returns_the_same_object(self):
        model = DemandLSTM(n_features=24, hidden_size=8, num_layers=1, horizon=48)
        settings = ForecastApiSettings(inference_optimization="none")
        result = apply_inference_optimization(model, settings)
        assert result is model

    def test_dynamic_quantization_preserves_output_shape_and_keys(self):
        model = DemandLSTM(n_features=24, hidden_size=8, num_layers=1, horizon=48)
        model.eval()
        settings = ForecastApiSettings(inference_optimization="dynamic_quantization")
        quantized = apply_inference_optimization(model, settings)

        x = torch.randn(1, 48, 24)
        with torch.no_grad():
            outputs, _ = quantized(x)
        assert set(outputs) == {"p50", "p10", "p90"}
        for head in outputs.values():
            assert head.shape == (1, 48)

    def test_dynamic_quantization_output_is_close_to_fp32(self):
        model = DemandLSTM(n_features=24, hidden_size=8, num_layers=1, horizon=48)
        model.eval()
        x = torch.randn(1, 48, 24)
        with torch.no_grad():
            fp32_out, _ = model(x)

        settings = ForecastApiSettings(inference_optimization="dynamic_quantization")
        quantized = apply_inference_optimization(model, settings)
        with torch.no_grad():
            quant_out, _ = quantized(x)

        # int8 quantization introduces small numerical error, not a
        # different answer -- this bounds it rather than requiring exact
        # equality.
        assert torch.allclose(fp32_out["p50"], quant_out["p50"], atol=0.5)
