"""Tests for ecolens.forecasting.training.losses (ECO-112)."""

from __future__ import annotations

import torch

from ecolens.forecasting.training.losses import DemandForecastLoss, pinball_loss


class TestPinballLoss:
    def test_zero_when_predictions_are_exact(self):
        target = torch.tensor([1.0, 2.0, 3.0])
        loss = pinball_loss(target, target, quantile=0.1)
        assert loss.item() == 0.0

    def test_low_quantile_penalizes_overprediction_more(self):
        target = torch.tensor([0.0])
        over = torch.tensor([1.0])  # prediction is 1 above target
        under = torch.tensor([-1.0])  # prediction is 1 below target
        q = 0.1
        over_loss = pinball_loss(over, target, quantile=q)
        under_loss = pinball_loss(under, target, quantile=q)
        # At a low quantile (aiming for the lower tail), overshooting the
        # target should cost more than undershooting by the same amount.
        assert over_loss.item() > under_loss.item()

    def test_high_quantile_penalizes_underprediction_more(self):
        target = torch.tensor([0.0])
        over = torch.tensor([1.0])
        under = torch.tensor([-1.0])
        q = 0.9
        over_loss = pinball_loss(over, target, quantile=q)
        under_loss = pinball_loss(under, target, quantile=q)
        assert under_loss.item() > over_loss.item()

    def test_median_quantile_is_symmetric(self):
        target = torch.tensor([0.0])
        over = torch.tensor([1.0])
        under = torch.tensor([-1.0])
        over_loss = pinball_loss(over, target, quantile=0.5)
        under_loss = pinball_loss(under, target, quantile=0.5)
        assert over_loss.item() == under_loss.item()


class TestDemandForecastLoss:
    def test_zero_when_all_heads_exact(self):
        loss_fn = DemandForecastLoss()
        target = torch.randn(4, 48)
        outputs = {"p50": target.clone(), "p10": target.clone(), "p90": target.clone()}
        total, components = loss_fn(outputs, target)
        assert total.item() == 0.0
        assert components["point_loss"] == 0.0

    def test_positive_when_predictions_are_off(self):
        loss_fn = DemandForecastLoss()
        target = torch.zeros(4, 48)
        outputs = {
            "p50": torch.ones(4, 48),
            "p10": torch.zeros(4, 48),
            "p90": torch.ones(4, 48) * 2,
        }
        total, components = loss_fn(outputs, target)
        assert total.item() > 0
        assert components["point_loss"] > 0

    def test_is_differentiable(self):
        loss_fn = DemandForecastLoss()
        target = torch.randn(4, 48)
        p50 = torch.randn(4, 48, requires_grad=True)
        p10 = torch.randn(4, 48, requires_grad=True)
        p90 = torch.randn(4, 48, requires_grad=True)
        total, _ = loss_fn({"p50": p50, "p10": p10, "p90": p90}, target)
        total.backward()
        assert p50.grad is not None
        assert p10.grad is not None
        assert p90.grad is not None
