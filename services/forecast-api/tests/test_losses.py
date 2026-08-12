"""`app/service/ml/losses.py` -- didn't have its own test file before
2026-08-12 (`train.py`'s own docstring implies loss coverage exists;
that claim was stale). Added alongside `demand_loss`'s Huber ->
pinball(0.5) change for its P50 term (`TODO.md` Phase 1) specifically
to pin the real property that change is for: pinball(0.5)'s population
minimizer is the conditional *median*, not the mean, unlike Huber.
"""

from __future__ import annotations

import inspect

import torch

from app.models.ml import DemandForecast
from app.service.ml.losses import demand_loss, huber_loss, pinball_loss


def test_pinball_loss_at_quantile_half_equals_half_mae():
    pred = torch.tensor([5.0, 5.0, 5.0])
    target = torch.tensor([3.0, 5.0, 9.0])

    result = pinball_loss(pred, target, 0.5)

    expected = 0.5 * torch.mean(torch.abs(target - pred))
    assert torch.isclose(result, expected)


def test_pinball_loss_penalizes_underprediction_more_for_a_high_quantile():
    target = torch.tensor([10.0])
    under = pinball_loss(torch.tensor([5.0]), target, 0.9)  # pred < target
    over = pinball_loss(torch.tensor([15.0]), target, 0.9)  # pred > target

    # `quantile=0.9` should punish under-prediction harder than an
    # equal-magnitude over-prediction -- the whole point of an
    # asymmetric quantile loss.
    assert under > over


def test_demand_loss_has_no_huber_delta_param_anymore():
    """Real bug this pins against regressing: an earlier version of
    `demand_loss` took a `huber_delta` kwarg no real caller ever passed
    (confirmed via grep before removing it) -- if it silently came back,
    that would signal the point head is back to being trained on Huber,
    not true pinball(0.5)."""
    assert "huber_delta" not in inspect.signature(demand_loss).parameters


def test_demand_loss_point_term_prefers_the_median_over_the_mean_on_skewed_targets():
    """The real property this whole change is for (`losses.py`'s own
    module docstring has the measured real-world bias it fixes):
    pinball(0.5)'s population minimizer is the conditional MEDIAN, not
    the mean -- unlike the Huber loss `demand_loss` used before
    2026-08-12. A skewed target set is exactly where median and mean
    diverge; if `demand_loss`'s point term is truly pinball(0.5),
    scoring it at the real median must beat scoring it at the real
    (much larger, skew-pulled) mean."""
    target = torch.tensor([1.0, 2.0, 3.0, 4.0, 100.0])
    median = torch.median(target)  # 3.0
    mean = torch.mean(target)  # 22.0
    horizon = target.shape[0]

    def forecast_at(point: torch.Tensor) -> DemandForecast:
        p = point.expand(horizon)
        return DemandForecast(p10=p - 1.0, p50=p, p90=p + 1.0)

    # `quantile_weight=0.0` zeroes the P10/P90 terms, isolating exactly
    # the point (P50) term this test is about.
    loss_at_median = demand_loss(forecast_at(median), target, quantile_weight=0.0)
    loss_at_mean = demand_loss(forecast_at(mean), target, quantile_weight=0.0)

    assert loss_at_median < loss_at_mean


def test_demand_loss_quantile_weight_only_scales_the_p10_p90_terms():
    """`quantile_weight` never touched P50's bias before this change and
    still doesn't after it (`losses.py`'s own docstring) -- the point
    term must be identical regardless of `quantile_weight` when P10/P90
    already exactly match the target (their own pinball terms are then
    each zero, so only the point term can differ)."""
    target = torch.tensor([10.0, 20.0, 30.0])
    forecast = DemandForecast(p10=target, p50=torch.tensor([5.0, 5.0, 5.0]), p90=target)

    loss_w0 = demand_loss(forecast, target, quantile_weight=0.0)
    loss_w5 = demand_loss(forecast, target, quantile_weight=5.0)

    assert torch.isclose(loss_w0, loss_w5)


def test_huber_loss_still_defined_and_usable_standalone():
    """`huber_loss` itself wasn't removed (`losses.py`'s own docstring:
    kept available for a future tuning experiment), only `demand_loss`
    stopped calling it -- a real regression check that it still works on
    its own, not dead/broken code left behind."""
    pred = torch.tensor([1.0, 2.0, 3.0])
    target = torch.tensor([1.5, 2.5, 3.5])

    result = huber_loss(pred, target)

    assert result.item() >= 0
