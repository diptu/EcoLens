"""`GET /v1/model/versions/{version}/evaluation` -- real walk-forward
backtest results (`ecolens-forecast evaluate`) for one registered
version, read from the separate MLflow run `ml/evaluate.py`'s
`evaluate_and_log` tags `evaluation=true` (`ml/registry.py`'s
`get_latest_evaluation`). Distinct from `ModelVersionOut.metrics`, which
only ever exposes the version's own training-time `test_mape` (the
easier, in-distribution split) -- this is the honest, harder
rolling-origin backtest against a real seasonal-naive baseline, per
region, per candidate (the version itself, its uncalibrated raw
quantiles, and the baseline)."""

from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class RegionEvaluationOut(AppBaseModel):
    region: str
    candidate: str
    mape: float
    rmse: float
    coverage: float
    # Real mean P10-P90 width in MW over this candidate's scored origins
    # (`ml/evaluate.py`'s `EvaluationReport.mean_interval_width`) -- the
    # dashboard Model Comparison page's "Consistency" metric.
    interval_width: float
    n_origins: int
    # `mae`/`mean_error` (2026-08-10, dashboard Model Performance page) --
    # `ml/evaluate.py`'s `EvaluationReport.mae`/`.mean_error`. `None` for
    # any real evaluation run logged before this field was added (the
    # underlying MLflow run simply never logged `eval_mae`/
    # `eval_mean_error` -- not an error, a real "this predates the field"
    # state, same as every other optional metric on this page).
    mae: float | None = None
    mean_error: float | None = None


class EvaluationSummaryOut(AppBaseModel):
    model_name: str
    version: str
    run_id: str
    evaluated_at: datetime
    n_origins: int
    regions: list[RegionEvaluationOut]


class EvaluationHistoryOut(AppBaseModel):
    """`GET /v1/model/versions/{version}/evaluation-history` -- every
    real evaluation run ever logged for one version, oldest first
    (`ml/registry.py`'s `get_evaluation_history`). The dashboard computes
    a "Stability (Performance Drift)" comparison from this directly
    (earliest vs. latest `eval_mape`) rather than this service
    pre-computing and storing a single drift score server-side."""

    model_name: str
    version: str
    runs: list[EvaluationSummaryOut]
