from __future__ import annotations

import pytest
import torch

from app.service.ml.losses import demand_loss, huber_loss, pinball_loss
from app.models.ml import DemandForecast


class TestHuberLoss:
    def test_zero_when_prediction_is_exact(self):
        pred = torch.tensor([5.0, 10.0])
        target = torch.tensor([5.0, 10.0])

        assert huber_loss(pred, target).item() == pytest.approx(0.0)

    def test_quadratic_within_delta(self):
        pred = torch.tensor([0.5])
        target = torch.tensor([0.0])

        # |error| = 0.5 <= delta=1.0 -> 0.5 * error^2
        assert huber_loss(pred, target, delta=1.0).item() == pytest.approx(0.125)

    def test_linear_beyond_delta(self):
        pred = torch.tensor([2.0])
        target = torch.tensor([0.0])

        # |error| = 2.0 > delta=1.0 -> delta * (|error| - 0.5*delta)
        assert huber_loss(pred, target, delta=1.0).item() == pytest.approx(1.5)


class TestPinballLoss:
    def test_zero_when_prediction_is_exact(self):
        pred = torch.tensor([10.0])
        target = torch.tensor([10.0])

        assert pinball_loss(pred, target, 0.9).item() == pytest.approx(0.0)

    def test_high_quantile_penalises_underprediction_more(self):
        under = pinball_loss(torch.tensor([8.0]), torch.tensor([10.0]), 0.9)
        over = pinball_loss(torch.tensor([12.0]), torch.tensor([10.0]), 0.9)

        assert under.item() == pytest.approx(1.8)
        assert over.item() == pytest.approx(0.2)
        assert under > over

    def test_low_quantile_penalises_overprediction_more(self):
        under = pinball_loss(torch.tensor([8.0]), torch.tensor([10.0]), 0.1)
        over = pinball_loss(torch.tensor([12.0]), torch.tensor([10.0]), 0.1)

        assert over.item() == pytest.approx(1.8)
        assert under.item() == pytest.approx(0.2)
        assert over > under


class TestDemandLoss:
    def test_zero_when_all_heads_match_target_exactly(self):
        target = torch.full((2, 4), 10.0)
        forecast = DemandForecast(p10=target, p50=target, p90=target)

        assert demand_loss(forecast, target).item() == pytest.approx(0.0)

    def test_quantile_weight_scales_only_the_pinball_terms(self):
        target = torch.full((1, 1), 10.0)
        forecast = DemandForecast(
            p10=torch.tensor([[9.0]]),
            p50=torch.tensor([[10.0]]),  # exact -> huber term is 0
            p90=torch.tensor([[11.0]]),
        )

        weighted_2x = demand_loss(forecast, target, quantile_weight=2.0)
        weighted_1x = demand_loss(forecast, target, quantile_weight=1.0)

        assert weighted_2x.item() == pytest.approx(2 * weighted_1x.item())
