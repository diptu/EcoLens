"""Read-only warehouse queries backing `/v1/forecast` inference and the
`/v1/emissions`/`POST /v1/footprint` endpoints.

`MARTS_SCHEMA`/`_TRAINING_COLUMNS` intentionally mirror `data-pipeline`'s
`app.service.ml.data` (same reasoning — `dbt`'s default schema-naming macro
puts `fct_energy_demand` in `raw_marts`, not a bare `marts` schema).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

IntensityMethod = Literal["live_provider", "live_mix_weighted"]

MARTS_SCHEMA = "raw_marts"

_TRAINING_COLUMNS = (
    "ts",
    "region",
    "demand_mw",
    "price_mwh",
    "total_generation_mw",
    "total_renewable_mw",
    "temp_c",
    "apparent_temp_c",
    "humidity_pct",
    "wind_speed_kmh",
)
_NUMERIC_TRAINING_COLUMNS = tuple(
    c for c in _TRAINING_COLUMNS if c not in ("ts", "region")
)


async def load_latest_window(
    db: AsyncSession, region: str, n_rows: int
) -> pd.DataFrame:
    """The most recent `n_rows` rows for `region`, ascending by `ts`.
    `service/ml/registry.py`'s inference path requests `lookback +
    max(lag/rolling windows)` rows so the lag/rolling features for the
    *last* `lookback` of them are fully populated (not `NaN` from
    feature-engineering warmup) once `ml.features.build_features` runs —
    same reasoning `ml.data.DemandDataset` (data-pipeline) applies at
    training time, just without a `Dataset` wrapper since inference only
    ever needs the single most recent window, not a sliding-window
    dataset.

    **Single-region caveat**: this only fetches `region`'s own rows, so
    `build_features`'s cross-region-context features
    (`total_demand_all_regions_mw`/`demand_share_of_total`) always come
    out as "region vs. itself" (share=1.0) here — consistent with v0
    training also being single-region only (`Settings.
    model_default_regions`), not a bug specific to serving. A genuinely
    multi-region model would need this to fetch every trained region's
    latest window, not just the one being forecast.
    """
    result = await db.execute(
        text(
            # nosec B608 -- `_TRAINING_COLUMNS`/`MARTS_SCHEMA` are fixed
            # module-level constants, not user input
            f"SELECT {', '.join(_TRAINING_COLUMNS)} "  # nosec B608
            f"FROM {MARTS_SCHEMA}.fct_energy_demand "
            "WHERE region = :region ORDER BY ts DESC LIMIT :n_rows"
        ),
        {"region": region, "n_rows": n_rows},
    )
    rows = result.mappings().all()
    df = pd.DataFrame(rows, columns=_TRAINING_COLUMNS)
    # asyncpg hands back Postgres `numeric` columns as `decimal.Decimal`
    # -- see `app.service.ml.data`'s (data-pipeline) identical cast for why
    # this has to happen before anything in `ml.features`/`ml.model`
    # touches these columns.
    df[list(_NUMERIC_TRAINING_COLUMNS)] = df[list(_NUMERIC_TRAINING_COLUMNS)].apply(
        pd.to_numeric
    )
    return df.sort_values("ts").reset_index(drop=True)


async def load_holidays(db: AsyncSession) -> pd.DataFrame:
    result = await db.execute(text("SELECT date, region FROM raw.aemo_holidays"))
    return pd.DataFrame(result.mappings().all(), columns=("date", "region"))


_INTENSITY_COLUMNS = (
    "hour",
    "region",
    "total_generation_mwh",
    "total_emissions_kgco2e",
    "intensity_kgco2e_per_mwh",
    "factors_version",
    "live_provider_intensity_kgco2e_per_mwh",
)


def resolve_intensity_method(
    hour, live_provider_intensity: float | None, freshness_minutes: float, *, now=None
) -> IntensityMethod:
    """`todo-model-training.md` Phase 7: real external-provider-first
    fallback -- `"live_provider"` if `fct_carbon_intensity.
    live_provider_intensity_kgco2e_per_mwh` is both non-null AND `hour`
    is within `freshness_minutes` of `now`, else `"live_mix_weighted"`.
    A stale-but-non-null provider figure is deliberately NOT trusted
    (the whole point of a freshness check) -- only a real, recent
    external number wins; anything else honestly falls back rather than
    silently serving a stale "live" figure.
    """
    if live_provider_intensity is None:
        return "live_mix_weighted"
    now = now or datetime.now(UTC)
    if hour.tzinfo is None:
        hour = hour.replace(tzinfo=UTC)
    age_minutes = (now - hour).total_seconds() / 60
    if age_minutes <= freshness_minutes:
        return "live_provider"
    return "live_mix_weighted"


async def load_latest_intensity(db: AsyncSession, region: str) -> dict | None:
    """The most recent `raw_marts.fct_carbon_intensity` hour for
    `region` — backs `GET /v1/emissions`."""
    result = await db.execute(
        text(
            f"SELECT {', '.join(_INTENSITY_COLUMNS)} FROM {MARTS_SCHEMA}.fct_carbon_intensity "  # nosec B608 -- fixed module-level constants, not user input
            "WHERE region = :region ORDER BY hour DESC LIMIT 1"
        ),
        {"region": region},
    )
    row = result.mappings().first()
    return dict(row) if row is not None else None


async def load_intensity_over_period(
    db: AsyncSession, region: str, start, end
) -> dict | None:
    """Generation-weighted average intensity across `[start, end]` —
    backs `POST /v1/footprint` (`README.md`'s `live_mix_weighted`
    method: `sum(emissions) / sum(generation)` over the period, not a
    plain average of each hour's already-weighted intensity, which would
    over-weight low-generation hours). Also returns the same real
    `provider_generation_mwh`/`provider_emissions_kgco2e` aggregates +
    `latest_hour` `load_current_intensity`/`load_ytd_intensity` do, so
    the route layer can apply `resolve_intensity_method`'s real
    freshness-gated fallback consistently everywhere (Phase 7)."""
    result = await db.execute(
        text(
            f"SELECT "  # nosec B608 -- `MARTS_SCHEMA` is a fixed module-level constant, not user input
            "sum(total_generation_mwh) AS total_generation_mwh, "
            "sum(total_emissions_kgco2e) AS total_emissions_kgco2e, "
            "sum(provider_generation_mwh) AS provider_generation_mwh, "
            "sum(provider_emissions_kgco2e) AS provider_emissions_kgco2e, "
            "max(hour) AS latest_hour, "
            "max(factors_version) AS factors_version "
            f"FROM {MARTS_SCHEMA}.fct_carbon_intensity "
            "WHERE region = :region AND hour >= :start AND hour <= :end"
        ),
        {"region": region, "start": start, "end": end},
    )
    row = result.mappings().first()
    if row is None or row["total_generation_mwh"] is None:
        return None
    return dict(row)


async def load_current_intensity(db: AsyncSession) -> dict | None:
    """All-region rollup of each region's *own* most recent hour —
    backs `GET /v1/emissions/current`. Deliberately not "the single
    latest hour across all regions" (`fct_carbon_intensity.hour`
    equality across all 6 regions isn't guaranteed — ingestion latency
    differs per source): `DISTINCT ON (region)` takes each region's own
    freshest row first, then sums those, same "latest available data
    per region" reasoning `GET /v1/forecast`'s `region=NEM` aggregate
    uses."""
    result = await db.execute(
        text(
            "WITH latest AS ("  # nosec B608 -- `MARTS_SCHEMA` below is a fixed module-level constant, not user input
            "  SELECT DISTINCT ON (region) "
            "    region, hour, total_generation_mwh, total_emissions_kgco2e, "
            "    provider_generation_mwh, provider_emissions_kgco2e, factors_version "
            f"  FROM {MARTS_SCHEMA}.fct_carbon_intensity "
            "  ORDER BY region, hour DESC"
            ") "
            "SELECT "
            "  sum(total_generation_mwh) AS total_generation_mwh, "
            "  sum(total_emissions_kgco2e) AS total_emissions_kgco2e, "
            "  sum(provider_generation_mwh) AS provider_generation_mwh, "
            "  sum(provider_emissions_kgco2e) AS provider_emissions_kgco2e, "
            "  max(hour) AS as_of, "
            "  max(hour) AS latest_hour, "
            "  max(factors_version) AS factors_version "
            "FROM latest"
        )
    )
    row = result.mappings().first()
    if row is None or row["total_generation_mwh"] is None:
        return None
    return dict(row)


async def load_demand_summary(db: AsyncSession, start, end) -> dict | None:
    """All-region period aggregate over `fct_energy_demand` — backs
    `GET /v1/demand/summary` (Renewable Share KPI + "Avg Wholesale
    Price"). `total_generation_mw`/`total_renewable_mw` are
    instantaneous (MW, not MWh) readings taken at each region's native
    reporting cadence — summing them ratio-of-sums-style (not averaging
    each interval's already-computed share) avoids over-weighting
    sparser-reporting regions, same reasoning
    `load_intensity_over_period`'s `live_mix_weighted` method uses for
    emissions intensity."""
    result = await db.execute(
        text(
            "SELECT "  # nosec B608 -- `MARTS_SCHEMA` below is a fixed module-level constant, not user input
            "  sum(total_generation_mw) AS total_generation_mw, "
            "  sum(total_renewable_mw) AS total_renewable_mw, "
            "  avg(price_mwh) AS avg_price_mwh "
            f"FROM {MARTS_SCHEMA}.fct_energy_demand "
            "WHERE ts >= :start AND ts <= :end"
        ),
        {"start": start, "end": end},
    )
    row = result.mappings().first()
    if row is None or row["total_generation_mw"] is None:
        return None
    return dict(row)


async def load_emissions_timeseries(
    db: AsyncSession, start, end, bucket: str, region: str | None = None
) -> list[dict]:
    """Emissions bucketed by `bucket` ("hour" or "day") — backs `GET
    /v1/emissions/timeseries`. `bucket` is validated by the route
    (`Literal["hour", "day"]`) before it ever reaches this function, so
    binding it straight into `date_trunc`'s first argument is safe —
    it's never raw user text. `region=None` aggregates across all
    regions (the original behavior); otherwise filtered to just that
    one, same optional-region convention `load_generation_mix` already
    uses."""
    where = "WHERE hour >= :start AND hour <= :end"
    params: dict = {"bucket": bucket, "start": start, "end": end}
    if region is not None:
        where += " AND region = :region"
        params["region"] = region

    result = await db.execute(
        text(
            "SELECT "  # nosec B608 -- `MARTS_SCHEMA` is a fixed constant; `where` is only ever built from fixed literal fragments above, values are bound params
            "  date_trunc(:bucket, hour) AS bucket, "
            "  sum(total_generation_mwh) AS total_generation_mwh, "
            "  sum(total_emissions_kgco2e) AS total_emissions_kgco2e, "
            "  CASE "
            "    WHEN sum(total_generation_mwh) IS NULL OR sum(total_generation_mwh) = 0 THEN NULL "
            "    ELSE sum(total_emissions_kgco2e) / sum(total_generation_mwh) "
            "  END AS intensity_kgco2e_per_mwh, "
            "  max(factors_version) AS factors_version "
            f"FROM {MARTS_SCHEMA}.fct_carbon_intensity "
            f"{where} "
            "GROUP BY date_trunc(:bucket, hour) "
            "ORDER BY bucket"
        ),
        params,
    )
    return [dict(row) for row in result.mappings().all()]


async def load_generation_mix(
    db: AsyncSession, start, end, region: str | None
) -> list[dict]:
    """Per-fuel-type generation + emissions over `[start, end]`, joined
    to `dim_energy_mix` for `category`/`is_renewable` — backs `GET
    /v1/generation-mix`. `region=None` aggregates across all regions;
    otherwise filtered to just that one."""
    where = "WHERE m.hour >= :start AND m.hour <= :end"
    params: dict = {"start": start, "end": end}
    if region is not None:
        where += " AND m.region = :region"
        params["region"] = region

    result = await db.execute(
        text(
            "SELECT "  # nosec B608 -- `MARTS_SCHEMA` is a fixed constant; `where` is only ever built from fixed literal fragments above, values are bound params
            "  m.fuel_type, "
            "  e.category, "
            "  e.is_renewable, "
            "  sum(m.total_generation_mwh) AS total_generation_mwh, "
            "  sum(m.total_emissions_kgco2e) AS total_emissions_kgco2e "
            f"FROM {MARTS_SCHEMA}.fct_generation_mix m "
            f"JOIN {MARTS_SCHEMA}.dim_energy_mix e ON m.fuel_type = e.fuel_type "
            f"{where} "
            "GROUP BY m.fuel_type, e.category, e.is_renewable "
            "ORDER BY total_emissions_kgco2e DESC NULLS LAST"
        ),
        params,
    )
    return [dict(row) for row in result.mappings().all()]


async def load_ytd_intensity(db: AsyncSession, start, end) -> dict | None:
    """All-region rollup across `[start, end]` — backs `GET
    /v1/emissions/ytd`. Same `sum(emissions) / sum(generation)`
    aggregation as `load_intensity_over_period`, just without the
    `region = :region` filter, since the Executive Dashboard's "Total
    CO2e (YTD)" KPI is a whole-of-platform figure, not a single
    region's."""
    result = await db.execute(
        text(
            f"SELECT "  # nosec B608 -- `MARTS_SCHEMA` is a fixed module-level constant, not user input
            "sum(total_generation_mwh) AS total_generation_mwh, "
            "sum(total_emissions_kgco2e) AS total_emissions_kgco2e, "
            "sum(provider_generation_mwh) AS provider_generation_mwh, "
            "sum(provider_emissions_kgco2e) AS provider_emissions_kgco2e, "
            "max(hour) AS latest_hour, "
            "max(factors_version) AS factors_version "
            f"FROM {MARTS_SCHEMA}.fct_carbon_intensity "
            "WHERE hour >= :start AND hour <= :end"
        ),
        {"start": start, "end": end},
    )
    row = result.mappings().first()
    if row is None or row["total_generation_mwh"] is None:
        return None
    return dict(row)
