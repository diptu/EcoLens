"""`GET /v1/model/versions/{version}/loss-curve` -- real per-epoch
`train_loss`/`val_loss`/`val_mape`/`val_rmse`/`val_mae` history for one
registered version, read from MLflow's step-metric history
(`ml/registry.py`'s `get_loss_curve`). Distinct from
`ModelVersionOut.metrics`, which only ever exposes each metric's *final*
logged value, not the curve over training.

`val_loss` (2026-08-05) is the real `demand_loss` on the validation
split, same units as `train_loss` -- the "training vs validation loss"
comparison the Performance page's chart is named for. `val_mape`/
`val_rmse`/`val_mae` stay separate from both: they're real MW-unit (or
percentage) error metrics, not losses, and plotting them against
`train_loss` on one axis would compare different units."""

from __future__ import annotations

from app.schemas.base import AppBaseModel


class LossCurvePointOut(AppBaseModel):
    epoch: int
    train_loss: float | None = None
    val_loss: float | None = None
    val_mape: float | None = None
    val_rmse: float | None = None
    val_mae: float | None = None


class LossCurveOut(AppBaseModel):
    model_name: str
    version: str
    run_id: str
    points: list[LossCurvePointOut]
