"""Orchestration for `/api/analytics/executive-kpis`: resolves the
period/region query params, queries the warehouse, and shapes the 6
KPI cards -- the only piece of this endpoint the route handler
(`api/read_routes.py`) calls into.

**3 of the 6 spec'd KPIs are real; 3 are honest "not yet available"
stubs, not fabricated numbers.** Total CO2e, Carbon Intensity, and
Renewable Share all have a real, already-dbt-tested column in
`fact_demand_30min` to compute from. Cost Savings, Compliance Score,
and Open Risks do not -- root TODO.md's Dashboard/Executive section
(Tier 3) already found and recorded this: no avoided-cost methodology,
no compliance-scoring model, and no risk-register data model exist
anywhere in this repo. Inventing plausible-looking numbers for an
*Executive* dashboard is a real harm (a wrong number shown as fact to a
decision-maker), not a shortcut -- see `_unavailable_kpi` below.

**Auth note:** the endpoint spec calls for a JWT bearer token from an
"iam-service" plus role-based 403s. No such service, JWT verification
library, or user/role model exists anywhere in this repo (verified —
no `jwt`/`jose` dependency, no auth middleware). The route this service
backs reuses this same app's existing `require_api_key` gate (see
`api/read_dependencies.py`) instead of fabricating JWT/RBAC
infrastructure that doesn't exist. Swap in real JWT verification once
an iam-service exists to verify against.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from ecolens.shared.observability.logging import get_logger

from ecolens.warehouse.core.periods import PERIOD_LABELS, resolve_period
from ecolens.warehouse.core.regions import resolve_region_group
from ecolens.warehouse.db.cache import Cache
from ecolens.warehouse.db.connection import ConnectionPool
from ecolens.warehouse.repository import queries
from ecolens.warehouse.schemas.executive_kpis import (
    ExecutiveKpisMeta,
    ExecutiveKpisResponse,
    KpiCard,
    PreviousPeriod,
    Trend,
)

log = get_logger(__name__)

_CACHE_KEY_PREFIX = "exec:kpis:v1"
# The literal spec gives a single fixed cache key ("exec:kpis:v1") with
# no room for period/region/currency -- can't be right, since those
# materially change the response; kept as a prefix here with the
# resolved params appended, so each distinct query still gets its own
# cached entry under the same versioned namespace.

# Below this, a delta reads as "flat" rather than "up"/"down" -- avoids
# a red/green flip on the UI for noise-level movement (e.g. 0.01%).
_FLAT_EPSILON_PCT = 0.05

_SPARKLINE_TARGET_POINTS = 10


def _cache_key(period: str, region: str, currency: str) -> str:
    return f"{_CACHE_KEY_PREFIX}:{period}:{region}:{currency}"


def _delta_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def _trend(delta_pct: float | None) -> Trend:
    if delta_pct is None:
        return "flat"
    if delta_pct > _FLAT_EPSILON_PCT:
        return "up"
    if delta_pct < -_FLAT_EPSILON_PCT:
        return "down"
    return "flat"


def _format_number(value: float | None, decimals: int = 0) -> str:
    if value is None:
        return "—"
    return f"{value:,.{decimals}f}"


def _downsample(
    values: list[float], target: int = _SPARKLINE_TARGET_POINTS
) -> list[float]:
    """`target`-ish evenly-sized-chunk averages -- a `ytd`/`qtd` daily
    series (up to ~365/~92 points) needs to fit the spec's "8-12 points
    for the optional inline mini-chart," while a `7d` series (7 points)
    already fits and passes through untouched.
    """
    if not values:
        return []
    if len(values) <= target:
        return [round(v, 4) for v in values]
    chunk_size = math.ceil(len(values) / target)
    chunks = [values[i : i + chunk_size] for i in range(0, len(values), chunk_size)]
    return [round(sum(chunk) / len(chunk), 4) for chunk in chunks if chunk]


def _series_values(series: list[dict[str, Any]], field: str) -> list[float]:
    return [row[field] for row in series if row.get(field) is not None]


def _total_co2e_kpi(
    period_label: str,
    current: dict[str, Any],
    previous: dict[str, Any],
    series: list[dict[str, Any]],
) -> KpiCard:
    value = current.get("total_carbon_tco2e")
    prev_value = previous.get("total_carbon_tco2e")
    delta = _delta_pct(value, prev_value)
    trend = _trend(delta)
    return KpiCard(
        id="total-co2e",
        label=f"Total CO₂e ({period_label})",
        value=round(value, 0) if value is not None else None,
        value_display=_format_number(value),
        unit="tCO₂e",
        delta_pct=delta,
        trend=trend,
        good_when="down",
        is_good=(trend == "down"),
        sub=(
            f"vs {_format_number(prev_value)} tCO₂e previous period"
            if prev_value is not None
            else "no prior-period data yet"
        ),
        sparkline=_downsample(_series_values(series, "total_carbon_tco2e")),
    )


def _carbon_intensity_kpi(
    current: dict[str, Any],
    previous: dict[str, Any],
    series: list[dict[str, Any]],
) -> KpiCard:
    value = current.get("avg_emissions_intensity_kgco2e_per_mwh")
    prev_value = previous.get("avg_emissions_intensity_kgco2e_per_mwh")
    delta = _delta_pct(value, prev_value)
    trend = _trend(delta)
    return KpiCard(
        id="carbon-intensity",
        label="Carbon Intensity",
        # kgCO2e/MWh == gCO2e/kWh numerically (kg/1000kWh*1000g/kg) --
        # no unit conversion, just a relabel of the same column
        # `get_national_summary`/`get_demand_summary` already expose.
        value=round(value, 0) if value is not None else None,
        value_display=_format_number(value),
        unit="g/kWh",
        delta_pct=delta,
        trend=trend,
        good_when="down",
        is_good=(trend == "down"),
        sub="average across the selected period",
        sparkline=_downsample(
            _series_values(series, "avg_emissions_intensity_kgco2e_per_mwh")
        ),
    )


def _renewable_share_kpi(
    current: dict[str, Any],
    previous: dict[str, Any],
    series: list[dict[str, Any]],
) -> KpiCard:
    value = current.get("avg_renewable_proportion")
    prev_value = previous.get("avg_renewable_proportion")
    delta = _delta_pct(value, prev_value)
    trend = _trend(delta)
    return KpiCard(
        id="renewable-share",
        label="Renewable Share",
        value=round(value, 1) if value is not None else None,
        value_display=_format_number(value, decimals=1),
        unit="%",
        delta_pct=delta,
        trend=trend,
        good_when="up",
        is_good=(trend == "up"),
        # RENEWABLE_CANONICAL_COLUMNS (ingestion/schema/openelectricity.py):
        # hydro + wind + solar (utility+rooftop) + biomass -- matches what
        # `renewable_proportion` is actually computed from at ingestion
        # time, not the spec example's "wind + solar + hydro" (which
        # omits biomass).
        sub="wind + solar + hydro + biomass, share of generation",
        sparkline=_downsample(_series_values(series, "avg_renewable_proportion")),
    )


def _unavailable_kpi(id_: str, label: str, *, unit: str, reason: str) -> KpiCard:
    """`trend`/`good_when` both `"flat"` (not e.g. `good_when="up"` with
    a `"flat"` trend, which the spec's own `is_good = trend === good_when`
    rule would then score as `False`/"bad") -- an unimplemented KPI
    should read as neutral on an Executive dashboard, not as a false
    red flag for something that was simply never measured.
    """
    return KpiCard(
        id=id_,
        label=label,
        value=None,
        value_display="—",
        unit=unit,
        delta_pct=None,
        trend="flat",
        good_when="flat",
        is_good=True,
        sub=reason,
        sparkline=[],
    )


async def build_executive_kpis(
    pool: ConnectionPool,
    cache: Cache | None,
    *,
    period: str,
    region: str,
    currency: str,
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    """Returns `(response_dict, cache_hit)`. `now`, if given, pins the
    period-window resolution for tests; production always omits it
    (real wall-clock time).
    """
    now = now or datetime.now(timezone.utc)
    cache_key = _cache_key(period, region, currency)

    if cache is not None:
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached, True

    window = resolve_period(period, now=now)
    region_group = resolve_region_group(region)

    current = await queries.get_carbon_summary(
        pool, region_group, window.current_since, window.current_until
    )
    previous = await queries.get_carbon_summary(
        pool, region_group, window.previous_since, window.previous_until
    )
    series = await queries.get_daily_carbon_series(
        pool, region_group, window.current_since, window.current_until
    )

    period_label = PERIOD_LABELS[period]
    kpis = [
        _total_co2e_kpi(period_label, current, previous, series),
        _carbon_intensity_kpi(current, previous, series),
        _renewable_share_kpi(current, previous, series),
        _unavailable_kpi(
            "cost-savings",
            "Cost Savings",
            unit=currency,
            reason="no cost-avoidance methodology implemented yet",
        ),
        _unavailable_kpi(
            "compliance-score",
            "Compliance Score",
            unit="/100",
            reason="no compliance-scoring model implemented yet",
        ),
        _unavailable_kpi(
            "open-risks",
            "Open Risks",
            unit="high",
            reason="no risk-register data model implemented yet",
        ),
    ]

    response = ExecutiveKpisResponse(
        meta=ExecutiveKpisMeta(
            period=period,
            region=region,
            currency=currency,
            as_of=window.current_until,
            previous_period=PreviousPeriod(
                start=window.previous_since, end=window.previous_until
            ),
            generated_at=now,
        ),
        kpis=kpis,
    )
    payload = response.model_dump(mode="json")

    if cache is not None:
        await cache.set(cache_key, payload)

    log.info(
        "analytics.executive_kpis.built",
        period=period,
        region=region,
        currency=currency,
        has_current_data=bool(current),
        has_previous_data=bool(previous),
    )
    return payload, False


__all__ = ["build_executive_kpis"]
