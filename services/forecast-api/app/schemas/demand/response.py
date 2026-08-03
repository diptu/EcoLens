from __future__ import annotations

from datetime import datetime
from typing import Literal

from app.schemas.base import AppBaseModel


class DemandSummaryResponse(AppBaseModel):
    """Backs `GET /v1/demand/summary` — an all-region period aggregate
    over `raw_marts.fct_energy_demand`. `renewable_share_pct` is a
    ratio-of-sums over instantaneous MW readings, not a true
    energy-weighted (MWh) share — see `service/ml/data.py`'s
    `load_demand_summary` for why. `avg_price_mwh` is a plain average of
    `price_mwh` over the period (not generation-weighted)."""

    since: datetime
    until: datetime
    renewable_share_pct: float | None = None
    avg_price_mwh: float | None = None
    method: Literal["mw_reading_ratio"] = "mw_reading_ratio"
