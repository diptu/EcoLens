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


class EvaluateModelRequest(AppBaseModel):
    """`POST /v1/model/versions/{version}/evaluate`'s body -- triggers
    `ecolens-forecast evaluate`'s real walk-forward backtest (`ml/
    evaluate.py`'s `evaluate_and_log`) over HTTP, the same way `POST
    /v1/model/train` already does for the CLI's `train` command.
    Previously CLI-only, so `GET .../evaluation` almost always returned
    `null` and the dashboard's Model Comparison page had nothing to show
    beyond a version's easier training-time `test_mape` -- see that
    endpoint's own docstring for why a real walk-forward run matters.

    Unlike training, a walk-forward backtest is real but comparatively
    cheap (inference over `n_origins` rolling windows per region, no
    gradient steps) -- safe to run synchronously in the request/response
    cycle rather than needing `train-worker`'s async dispatch.

    `regions`/`horizon`/`n_origins` all optional, defaulting to
    `evaluate_and_log`'s own defaults (`Settings.model_default_regions`,
    the registered version's own horizon, 10 origins).
    """

    model_name: str | None = None
    # `None` defaults to `"lstm"`, same server-side default `TrainRequest.
    # architecture` uses. `"timesfm_correction"` dispatches to
    # `evaluate_timesfm_correction_and_log` (the registered Ridge
    # residual-correction layer's own real walk-forward evaluate, same
    # `EvaluationRunResult` shape as the lstm/tft paths) -- distinct from
    # raw zero-shot TimesFM's `evaluate_timesfm_and_log`, which has a
    # fundamentally different signature (no registered version to load;
    # it downloads a pinned HuggingFace checkpoint directly) and stays
    # CLI-only (`ecolens-forecast evaluate-timesfm`), not reachable here.
    architecture: Literal["lstm", "tft", "timesfm_correction"] | None = None
    regions: list[str] | None = None
    horizon: int | None = None
    n_origins: int = 10


class TrainRequest(AppBaseModel):
    """`POST /v1/model/train`'s body -- `regions`/`window_hours` optional,
    defaulting to `Settings.model_default_regions`/
    `incremental_train_window_hours`, the same defaults the automatic
    (dbt-build-triggered) path falls back to. Ported from data-pipeline's
    identical schema as part of the training-code migration.

    `architecture` (`None` defaults to `"lstm"` server-side, same as the
    automatic path's own default) selects which incremental trainer
    `app.service.training_worker.handle_training_trigger` dispatches
    to -- `"lstm"`, `"tft"`, or `"timesfm_correction"` (the Ridge
    residual-correction layer on top of frozen TimesFM, `service/ml/
    timesfm_correction.py`; TimesFM's own weights are never retrained,
    only this layer is). Previously missing entirely: this endpoint
    always published `architecture: "lstm"` regardless of which
    architecture tab the dashboard's Fine-tune form had selected, so
    picking TFT or TimesFM and clicking "Start fine-tune" silently
    fine-tuned LSTM instead (`services/dashboard`'s `models/page.tsx`
    documented this as a known caveat before this field existed)."""

    regions: list[str] | None = None
    window_hours: int | None = None
    architecture: Literal["lstm", "tft", "timesfm_correction"] | None = None
    # 2026-08-11, real feature -- previously the dashboard's "Train a new
    # version" tab had no trigger endpoint at all, just a disabled
    # preview button. `False` (default) keeps the existing warm-started
    # incremental fine-tune path (`training_worker.handle_training_
    # trigger` -> `ml.incremental`/`ml.incremental_tft`); `True`
    # dispatches to the real from-scratch trainer instead
    # (`ml.train.train_and_register`/`ml.train_tft.train_and_register_
    # tft` -- the same functions `ecolens-forecast train`/`train-tft`
    # already call, now reachable over HTTP too). No real distinction
    # for `architecture="timesfm_correction"`: its own "incremental"
    # path already re-fits the Ridge correction layer fresh on the
    # selected window every time (frozen zero-shot TimesFM has no
    # weights to warm-start from) -- accepted but doesn't change its
    # dispatch, see `handle_training_trigger`'s own comment.
    full_retrain: bool = False
