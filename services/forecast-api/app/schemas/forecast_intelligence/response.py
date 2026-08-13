"""`GET /v1/forecast/intelligence` -- the response shape
`todo-model-training.md`'s "combined forecast + generation-mix +
carbon-intelligence endpoint" section originally scoped as an
approximation (`generation_mix_method: "current_share_scaled_by_
demand_forecast"` -- hold today's real mix share constant, scale by the
demand forecast). This is the real thing instead:
`EnergyForecastLSTM` genuinely predicts per-bucket generation, not an
approximation of it -- `generation_mix_method` reports
`"model_predicted_reconciled"` accordingly (predicted independently per
bucket, then `reconciliation.reconcile_generation` rescales the mix so
it sums to the predicted demand).

`gCO2e/kWh` vs. this platform's usual `kgCO2e/MWh`: numerically
identical (kg/MWh = g/kWh) -- a direct unit alias, not a real
conversion, same convention `todo-model-training.md`'s original spec
already established for this endpoint.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class QuantileValue(AppBaseModel):
    p10: float
    p50: float
    p90: float


class ForecastIntelligencePoint(AppBaseModel):
    ts: datetime
    electricity_demand_mw: QuantileValue
    #: Keyed by bucket name (`coal`/`gas`/`wind`/`solar`/`other` --
    #: `energy_features.GENERATION_TARGET_COLUMNS`' order, stripped of
    #: its `_mw` suffix).
    generation_mix_breakdown_mw: dict[str, QuantileValue]
    emissions_kg: QuantileValue
    carbon_intensity_gco2e_per_kwh: QuantileValue
    #: Derived from the P50 generation mix only: `(wind + solar) /
    #: total`. Deliberately excludes the `other` bucket's real hydro/
    #: biomass share from the numerator -- `other` mixes renewable
    #: (hydro, biomass) with non-renewable (distillate) and storage
    #: (pumped_hydro, battery_discharge) generation, and the model
    #: doesn't predict a finer split within it (the 4-named-buckets +
    #: catch-all scope decision -- see `int_demand_with_weather.sql`'s
    #: own generation-bucket comment). Undercounting real renewable
    #: share this way is a conservative, honestly-scoped approximation,
    #: not a claim of precision `other`'s own composition can't support.
    renewable_proportion_derived: float


class ForecastIntelligenceMetadata(AppBaseModel):
    #: This model has no conformal calibration this pass
    #: (`ml/train_energy_forecast.py`'s own module docstring) -- always
    #: `False` here, genuinely (not the `/v1/forecast`-inherited
    #: always-`True` the original spec assumed before this became a
    #: real, separate, uncalibrated model).
    conformal_calibration_applied: Literal[False] = False
    generation_mix_method: Literal["model_predicted_reconciled"] = "model_predicted_reconciled"


class ForecastIntelligenceResponse(AppBaseModel):
    region: str
    model: str
    generated_at: datetime
    horizon: str
    interval: str
    metadata: ForecastIntelligenceMetadata
    points: list[ForecastIntelligencePoint]
