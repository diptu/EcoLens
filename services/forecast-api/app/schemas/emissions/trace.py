from __future__ import annotations

from datetime import datetime

from app.schemas.base import AppBaseModel


class EmissionsTraceFuelBreakdown(AppBaseModel):
    """One fuel's contribution to one interval's aggregate intensity —
    the real per-fuel row `raw_marts.fct_generation_mix` holds,
    unmodified. `effective_factor_kgco2e_per_mwh` is derived
    (`emissions_kgco2e / generation_mwh`), not a separate warehouse
    column — the actual weighted-average factor this fuel's generation
    was charged at for this interval, after `services/waerehouse`'s own
    per-fuel emission-factor weighting (`README`'s "live_mix_weighted"
    method) already ran."""

    fuel_type: str
    generation_mwh: float
    emissions_kgco2e: float
    effective_factor_kgco2e_per_mwh: float | None = None


class EmissionsTraceInterval(AppBaseModel):
    """One hour's real `raw_marts.fct_carbon_intensity` row plus the
    `raw_marts.fct_generation_mix` rows that sum into it — the actual
    calculation chain underlying that hour's `intensity_kgco2e_per_mwh`,
    not a re-derivation or approximation of it."""

    hour: datetime
    total_generation_mwh: float | None = None
    total_emissions_kgco2e: float | None = None
    intensity_kgco2e_per_mwh: float | None = None
    factors_version: str | None = None
    by_fuel: list[EmissionsTraceFuelBreakdown]


class EmissionsTraceResponse(AppBaseModel):
    """Backs `GET /v1/emissions/trace` — the Carbon Methodology page's
    "show me the real numbers behind this calculation" feature
    (`carbon/methodology/page.tsx`'s `TraceMockup`, which this replaces).
    Every number here is read straight from the warehouse, not
    recomputed or approximated — `total_emissions_kgco2e` /
    `total_generation_mwh` on each interval already equal the sum of
    that interval's own `by_fuel` rows (same source, no double
    accounting)."""

    region: str
    generated_at: datetime
    intervals: list[EmissionsTraceInterval]
