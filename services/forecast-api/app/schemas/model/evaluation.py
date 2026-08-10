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
    n_origins: int


class EvaluationSummaryOut(AppBaseModel):
    model_name: str
    version: str
    run_id: str
    evaluated_at: datetime
    n_origins: int
    regions: list[RegionEvaluationOut]
