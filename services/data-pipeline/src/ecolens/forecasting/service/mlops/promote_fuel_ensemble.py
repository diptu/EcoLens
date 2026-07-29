"""Promotion policy for `model/fuel_ensemble.py`'s per-fuel LightGBM
ensemble -- same "nothing reaches serving without going through the
promote/rollback gate" principle root TODO.md's Validation section states
for the demand models, applied to a metric shape `mlops/promote.py`'s
`decide()` doesn't fit: that module is typed against `FullEvaluation`
(the quantile/MAPE evaluation the LSTM/TFT/TimesFM share), while the fuel
ensemble's own evaluation is a plain per-fuel MAE dict (16 independent
LightGBM regressors, no quantile heads, no MAPE). A separate module here
rather than widening `promote.py` itself to accept either shape -- that
module is small, already well-tested, and used by three call sites; a
metric-shape parameter or `Protocol` for "one more case" would be more
indirection than the one new caller here is worth.

Policy is otherwise identical: promote iff the challenger's mean test MAE
(across all 16 fuels) is strictly better than the current production
version's own recorded `test_mae_mean` metric. No production version yet
-> always promote.
"""

from __future__ import annotations

from dataclasses import dataclass

from ecolens.shared.observability.logging import get_logger

from .registry import ModelRegistry, RegisteredVersion

log = get_logger(__name__)


@dataclass(frozen=True)
class FuelEnsemblePromotionDecision:
    promote: bool
    reason: str
    challenger_mae: float
    current_production_mae: float | None


def decide(
    registry: ModelRegistry,
    challenger: RegisteredVersion,
    challenger_test_mae_mean: float,
    *,
    alias: str,
) -> FuelEnsemblePromotionDecision:
    current = registry.get_by_alias(alias)
    if current is None:
        return FuelEnsemblePromotionDecision(
            promote=True,
            reason=f"no version currently holds alias {alias!r}",
            challenger_mae=challenger_test_mae_mean,
            current_production_mae=None,
        )

    current_run = registry.client.get_run(current.run_id)
    current_mae = current_run.data.metrics.get("test_mae_mean")
    if current_mae is None:
        return FuelEnsemblePromotionDecision(
            promote=True,
            reason=(
                f"current {alias!r} version {current.version} has no recorded "
                "test_mae_mean to compare against"
            ),
            challenger_mae=challenger_test_mae_mean,
            current_production_mae=None,
        )

    if challenger_test_mae_mean < current_mae:
        return FuelEnsemblePromotionDecision(
            promote=True,
            reason=(
                f"challenger mean MAE {challenger_test_mae_mean:.3f} beats "
                f"current {current_mae:.3f}"
            ),
            challenger_mae=challenger_test_mae_mean,
            current_production_mae=current_mae,
        )
    return FuelEnsemblePromotionDecision(
        promote=False,
        reason=(
            f"challenger mean MAE {challenger_test_mae_mean:.3f} does not beat "
            f"current {current_mae:.3f}"
        ),
        challenger_mae=challenger_test_mae_mean,
        current_production_mae=current_mae,
    )


def promote_if_better(
    registry: ModelRegistry,
    challenger: RegisteredVersion,
    challenger_test_mae_mean: float,
    *,
    alias: str,
) -> FuelEnsemblePromotionDecision:
    decision = decide(registry, challenger, challenger_test_mae_mean, alias=alias)
    if decision.promote:
        registry.set_alias(alias, challenger.version)
        log.info(
            "promote_fuel_ensemble.applied",
            version=challenger.version,
            alias=alias,
            reason=decision.reason,
        )
    else:
        log.info(
            "promote_fuel_ensemble.skipped",
            version=challenger.version,
            alias=alias,
            reason=decision.reason,
        )
    return decision


__all__ = ["FuelEnsemblePromotionDecision", "decide", "promote_if_better"]
