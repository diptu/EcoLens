"""Real emission factors for `CarbonEngine`'s 5 generation-mix buckets
(coal/gas/wind/solar/other), replacing `services/forecast-api/notebooks/
lstm.ipynb`'s illustrative example dict
(`{"coal": 850.0, "gas": 400.0, "wind": 10.0, "solar": 40.0}`).

`dim_energy_mix.intensity_kgco2e_per_mwh` already has real, sourced,
versioned per-fuel-type factors (`seeds/emissions_factors.csv`, DCCEEW
National Greenhouse Accounts Factors, NGER 2025-Q4) -- kgCO2e/MWh is
numerically identical to gCO2e/kWh (kg/MWh = g/kWh), the unit
`CarbonEngine` expects, so no conversion is needed, only bucketing.

Two of the 5 buckets (coal, gas, wind) map 1:1 onto a single
`dim_energy_mix.fuel_type` each, so their factor is exact. `solar` and
`other` each combine multiple fuel_types with genuinely different real
factors -- `other` especially: `distillate` is 770 kgCO2e/MWh vs. the
rest of `other`'s members (hydro 5, biomass 0, pumped_hydro 0,
battery_discharge 0) being near-zero. A flat unweighted average of those
factor *values* would be badly wrong (~155, dominated by distillate's
outlier value) -- confirmed against real historical generation from
`services/ingestion`'s `master.duckdb` (107K rows, a full year): real
average MW is ~265 (hydro) vs ~0.4 (distillate), i.e. distillate is a
rarely-dispatched peaking fuel, not a meaningful share of real "other"
generation. The correct blend weights each fuel_type's factor by its
own *real generation volume*, not a bare average of the factor numbers.
Real-data check (`master.duckdb` averages fed through this exact
weighting formula): other's blended factor comes out to ~4.3 kgCO2e/MWh
-- close to hydro's 5, as expected once correctly weighted, not the
~155 a naive average would have produced.

`GENERATION_BUCKET_FUEL_TYPES` must stay in sync by hand with
`services/waerehouse/dbt/ecolens/models/intermediate/
int_demand_with_weather.sql`'s own coal_mw/gas_mw/wind_mw/solar_mw/
other_mw bucketing SQL -- same reasoning as `app/models/
energy_forecast_lstm.py`'s cross-service duplication note, just cross-
layer (dbt SQL vs. this Python mapping) instead of cross-service.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

MARTS_SCHEMA = "raw_marts"

# Keep in sync with int_demand_with_weather.sql's generation CTE.
GENERATION_BUCKET_FUEL_TYPES: dict[str, tuple[str, ...]] = {
    "coal": ("coal",),
    "gas": ("gas",),
    "wind": ("wind",),
    "solar": ("solar_utility", "solar_rooftop"),
    "other": ("hydro", "biomass", "distillate", "pumped_hydro", "battery_discharge"),
}

DEFAULT_LOOKBACK_DAYS = 90


def compute_bucket_factors(
    intensity_by_fuel_type: dict[str, float],
    generation_mw_by_fuel_type: dict[str, float],
) -> dict[str, float]:
    """Pure function, no DB dependency -- generation-weighted average
    factor per bucket: `sum(weight_i * factor_i) / sum(weight_i)` over
    each bucket's member fuel_types.

    Falls back to a plain (unweighted) mean of the member factors for a
    bucket if every member has zero/missing real generation weight (no
    real data yet to weight by) -- an honest degraded fallback, not
    silently producing 0 or raising, matching this platform's established
    convention of falling back to a documented approximation rather than
    failing when real weighting data is temporarily unavailable
    (`stg_openelectricity_mix.sql`'s own `renewable_mw_source` fallback
    is the same pattern one layer down).
    """
    result: dict[str, float] = {}
    for bucket, fuel_types in GENERATION_BUCKET_FUEL_TYPES.items():
        members = [ft for ft in fuel_types if ft in intensity_by_fuel_type]
        if not members:
            continue

        weighted_sum = 0.0
        total_weight = 0.0
        for ft in members:
            weight = max(generation_mw_by_fuel_type.get(ft, 0.0), 0.0)
            weighted_sum += weight * intensity_by_fuel_type[ft]
            total_weight += weight

        if total_weight > 0:
            result[bucket] = weighted_sum / total_weight
        else:
            result[bucket] = sum(intensity_by_fuel_type[ft] for ft in members) / len(members)

    return result


async def load_generation_bucket_factors(
    db: AsyncSession, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> dict[str, float]:
    """Real query: `dim_energy_mix` for factors (exact, versioned,
    doesn't change per-request) + `fct_generation_mix`'s
    `total_generation_mwh` summed over the last `lookback_days` for
    weights (real recent generation mix, not a fixed/stale snapshot).
    `lookback_days=90` balances "recent enough to reflect the current
    real mix" against "long enough that one unusual day doesn't swing
    the blended 'other' factor" -- not tuned against a specific incident,
    a reasonable starting default.
    """
    factors_result = await db.execute(
        text(f"SELECT fuel_type, intensity_kgco2e_per_mwh FROM {MARTS_SCHEMA}.dim_energy_mix")  # nosec B608 -- fixed module-level constant, not user input
    )
    intensity_by_fuel_type = {row.fuel_type: float(row.intensity_kgco2e_per_mwh) for row in factors_result}

    weights_result = await db.execute(
        text(
            "SELECT fuel_type, sum(total_generation_mwh) AS total_mwh "  # nosec B608 -- fixed module-level constant, not user input
            f"FROM {MARTS_SCHEMA}.fct_generation_mix "
            "WHERE hour >= now() - make_interval(days => :lookback_days) "
            "GROUP BY fuel_type"
        ),
        {"lookback_days": lookback_days},
    )
    generation_mw_by_fuel_type = {
        row.fuel_type: float(row.total_mwh) for row in weights_result if row.total_mwh is not None
    }

    return compute_bucket_factors(intensity_by_fuel_type, generation_mw_by_fuel_type)
