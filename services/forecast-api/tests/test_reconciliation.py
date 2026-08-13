from __future__ import annotations

import pytest
import torch

from app.service.ml.reconciliation import reconcile_generation


class TestReconcileGeneration:
    def test_sums_to_demand_across_sources(self):
        demand = torch.tensor([[[6000.0]]])  # [B=1, H=1, Q=1]
        generation = torch.tensor([[[[2000.0], [1500.0], [1000.0], [500.0], [1000.0]]]])  # [1,1,S=5,1]

        reconciled = reconcile_generation(demand, generation)

        assert torch.allclose(reconciled.sum(dim=2), demand, atol=1e-3)

    def test_preserves_relative_shares(self):
        demand = torch.tensor([[[6000.0]]])
        generation = torch.tensor([[[[4000.0], [2000.0], [0.0], [0.0], [0.0]]]])

        reconciled = reconcile_generation(demand, generation)

        # Original ratio was 2:1 between the first two sources -- should
        # still be 2:1 after rescaling.
        ratio = reconciled[0, 0, 0, 0] / reconciled[0, 0, 1, 0]
        assert ratio.item() == pytest.approx(2.0, rel=1e-3)

    def test_handles_zero_total_generation_without_dividing_by_zero(self):
        demand = torch.tensor([[[5000.0]]])
        generation = torch.zeros(1, 1, 5, 1)

        reconciled = reconcile_generation(demand, generation)

        assert torch.isfinite(reconciled).all()

    def test_multi_quantile_and_multi_horizon_shapes_preserved(self):
        demand = torch.rand(2, 4, 3) * 5000
        generation = torch.rand(2, 4, 5, 3) * 1000

        reconciled = reconcile_generation(demand, generation)

        assert reconciled.shape == generation.shape
        assert torch.allclose(reconciled.sum(dim=2), demand, atol=1e-2)
