from __future__ import annotations

from typing import Literal

from app.schemas.base import AppBaseModel


class PromoteModelRequest(AppBaseModel):
    """`POST /v1/model/versions/{version}/promote`'s body. `model_name`
    (`todo-model-training.md` Phase 8) is optional -- `None` (the
    default) promotes a version of `Settings.mlflow_registry_model_name`
    (`lstm_demand`, unchanged existing behavior); pass e.g.
    `lstm_demand_tft` to promote a TFT version instead, now that more
    than one architecture is really registered.

    `force` (default `False`) skips only the single-scalar `test_mape`
    regression gate -- never the `eval_gate_passed` live-evaluation gate,
    which stays a hard block regardless. Real need this surfaced for: a
    multi-region model's *blended* `test_mape` across all its regions
    can fail the gate against a single-region Production version even
    when every region but one is a real improvement -- `test_mape` alone
    can't see that breakdown, only a real per-region walk-forward
    evaluation (`ecolens-forecast evaluate`) can. `force` exists for that
    reviewed-by-a-human case, not to make the gate meaningless -- it's
    still the default-off path."""

    stage: Literal["Production", "Staging", "Archived"]
    model_name: str | None = None
    force: bool = False


class TrainRequest(AppBaseModel):
    """`POST /v1/model/train`'s body -- both fields optional, defaulting
    to `Settings.model_default_regions`/`incremental_train_window_hours`,
    the same defaults the automatic (dbt-build-triggered) path falls
    back to. Ported from data-pipeline's identical schema as part of the
    training-code migration."""

    regions: list[str] | None = None
    window_hours: int | None = None
