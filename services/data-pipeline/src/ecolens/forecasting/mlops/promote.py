"""ECO-115 (promotion policy): decides whether a newly-trained
challenger model version should take over the `production` alias from
whatever's currently there.

Policy is deliberately simple and stated once, not buried in the
training loop: promote if and only if the challenger's test MAPE is
strictly better than the current production version's *last recorded*
MAPE (from that version's own MLflow run metrics -- re-scoring it here
would need the exact same held-out test split it was itself evaluated
on, which isn't guaranteed given each training run gets a fresh
chronological split off whatever snapshot triggered it). No production
version yet -> always promote (there's nothing to beat).
"""

from __future__ import annotations

from dataclasses import dataclass

from mlflow.tracking import MlflowClient

from ecolens.shared.observability.logging import get_logger

from ..evaluation.evaluate import FullEvaluation
from .registry import ModelRegistry, RegisteredVersion

log = get_logger(__name__)


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reason: str
    challenger_mape: float
    current_production_mape: float | None


def _mape_for_run(client: MlflowClient, run_id: str) -> float | None:
    run = client.get_run(run_id)
    return run.data.metrics.get("test_mape")


def decide(
    registry: ModelRegistry,
    challenger: RegisteredVersion,
    challenger_evaluation: FullEvaluation,
    *,
    alias: str,
) -> PromotionDecision:
    """Pure decision function -- does not mutate the registry. Call
    `apply()` (or `set_alias` directly) if `decision.promote` is True.
    """
    challenger_mape = challenger_evaluation.point.overall["mape"]
    current = registry.get_by_alias(alias)

    if current is None:
        return PromotionDecision(
            promote=True,
            reason=f"no version currently holds alias {alias!r}",
            challenger_mape=challenger_mape,
            current_production_mape=None,
        )

    current_mape = _mape_for_run(registry.client, current.run_id)
    if current_mape is None:
        return PromotionDecision(
            promote=True,
            reason=(
                f"current {alias!r} version {current.version} has no recorded "
                "test_mape to compare against"
            ),
            challenger_mape=challenger_mape,
            current_production_mape=None,
        )

    if challenger_mape < current_mape:
        return PromotionDecision(
            promote=True,
            reason=f"challenger MAPE {challenger_mape:.3f} beats current {current_mape:.3f}",
            challenger_mape=challenger_mape,
            current_production_mape=current_mape,
        )
    return PromotionDecision(
        promote=False,
        reason=f"challenger MAPE {challenger_mape:.3f} does not beat current {current_mape:.3f}",
        challenger_mape=challenger_mape,
        current_production_mape=current_mape,
    )


def promote_if_better(
    registry: ModelRegistry,
    challenger: RegisteredVersion,
    challenger_evaluation: FullEvaluation,
    *,
    alias: str,
) -> PromotionDecision:
    """`decide()` plus actually applying it -- the one call a training/
    evaluation job needs.
    """
    decision = decide(registry, challenger, challenger_evaluation, alias=alias)
    if decision.promote:
        registry.set_alias(alias, challenger.version)
        log.info(
            "promote.applied",
            version=challenger.version,
            alias=alias,
            reason=decision.reason,
        )
    else:
        log.info(
            "promote.skipped",
            version=challenger.version,
            alias=alias,
            reason=decision.reason,
        )
    return decision


__all__ = ["PromotionDecision", "decide", "promote_if_better"]
