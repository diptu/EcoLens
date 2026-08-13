"""Loads `EnergyForecastLSTM` training data from the R2-hosted
`master.duckdb` (`services/ingestion`'s offline training artifact,
`s3://<bucket>/training/master.duckdb`) instead of the live Postgres
warehouse marts.

Why this exists: `train_energy_forecast.train_and_register_energy_forecast`
reads `{MARTS_SCHEMA}.fct_energy_demand` (`energy_data.
load_energy_training_data`), which requires `services/waerehouse`'s dbt
build to have materialized real marts in the target Postgres. As of
2026-08-08 the Postgres this service's own `.env` points at has no
`raw_marts` schema at all and empty `raw.*` tables -- there is nothing to
train against there yet. `master.duckdb` (built by `services/ingestion/
scripts/build_master_table.py` from real landed AEMO/OpenElectricity/BoM
data, already used for the real, executed feature selection this
service's `energy_features.py` is reconciled against -- see that
module's own docstring) is real historical data that exists right now,
so this is the bootstrap path for the model's first-ever trained version.

Produces a DataFrame in exactly `energy_data.py`'s
`_ENERGY_TRAINING_COLUMNS` shape, so `train_energy_forecast.
train_energy_model` (and the `energy_features.build_features`/
`FEATURE_COLUMNS` pipeline it calls) run completely unmodified against
this data source too -- only the loader differs, not the training code.

Generation-mix buckets (`coal_mw`/`gas_mw`/`wind_mw`/`solar_mw`/
`other_mw`) are built from `master.duckdb`'s `oe_*` columns using
`emission_factors.GENERATION_BUCKET_FUEL_TYPES` -- the same canonical
bucket definition `CarbonEngine` uses for real inference, not a
separately-invented mapping.

forecast-api has no R2 config of its own (`app/core/config.py` has none)
-- this reuses `services/ingestion/.env`'s `CLOUDFLARESTORAGE_*`
credentials directly, the same cross-service credential reuse
`services/ingestion/notebooks/feature-selection.ipynb`'s own R2-pull cell
already does (and for the same reason: forecast-api and ingestion are
separate installs, so this avoids importing ingestion's package just to
read 4 env vars).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

import duckdb
import pandas as pd

from app.service.ml.emission_factors import GENERATION_BUCKET_FUEL_TYPES
from app.service.ml.energy_features import GENERATION_TARGET_COLUMNS

_INGESTION_DIR = Path(__file__).resolve().parents[4] / "ingestion"
_INGESTION_ENV = _INGESTION_DIR / ".env"
_LOCAL_CACHE = _INGESTION_DIR / "data" / "training" / "master.duckdb"
_R2_KEY = "training/master.duckdb"

REGIONS_ALL: tuple[str, ...] = ("NSW1", "QLD1", "SA1", "TAS1", "VIC1", "WEM")


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal `KEY=VALUE` `.env` parser -- avoids adding a
    `python-dotenv` dependency to this service for the 4 keys this
    module actually needs. Ignores blank lines/`#` comments; strips
    matching surrounding quotes, same as `python-dotenv`'s own default
    behavior for unexported values."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def _r2_config() -> dict[str, str] | None:
    """`services/ingestion/.env`'s R2 credentials, resolved with the same
    precedence/fallback logic as `ingestion.app.core.config.Settings`'s
    `object_storage_*` properties -- duplicated rather than imported (see
    module docstring)."""
    if not _INGESTION_ENV.exists():
        return None
    env = _parse_env_file(_INGESTION_ENV)
    access_key = env.get("CLOUDFLARESTORAGE_ACCESS_KEY_ID")
    secret_key = env.get("CLOUDFLARESTORAGE_SECRET_ACCESS_KEY")
    if not access_key or not secret_key:
        return None

    s3_api = env.get("CLOUDFLARESTORAGE_S3_API", "")
    account_id = env.get("CLOUDFLARESTORAGE_ACCOUNT_ID")
    if s3_api:
        parsed = urlparse(s3_api)
        endpoint_url = f"{parsed.scheme}://{parsed.netloc}"
        bucket = parsed.path.strip("/") or "ecolens"
    elif account_id:
        endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"
        bucket = "ecolens"
    else:
        return None

    return {
        "endpoint_url": endpoint_url,
        "bucket": bucket,
        "access_key": access_key,
        "secret_key": secret_key,
    }


def ensure_master_table(*, force_refresh: bool = False) -> Path:
    """Local path to `master.duckdb`, downloading from R2 first if
    missing (or `force_refresh=True`). Falls back to an existing local
    cache if R2 isn't configured -- same "disposable cache, real source
    is R2" contract `feature-selection.ipynb`'s own R2 cell documents."""
    if _LOCAL_CACHE.exists() and not force_refresh:
        return _LOCAL_CACHE

    config = _r2_config()
    if config is None:
        if _LOCAL_CACHE.exists():
            return _LOCAL_CACHE
        raise RuntimeError(
            f"master.duckdb not found locally at {_LOCAL_CACHE} and R2 isn't "
            f"configured (checked {_INGESTION_ENV} for CLOUDFLARESTORAGE_* "
            "credentials) -- cannot fetch it."
        )

    import boto3

    _LOCAL_CACHE.parent.mkdir(parents=True, exist_ok=True)
    s3 = boto3.client(
        "s3",
        endpoint_url=config["endpoint_url"],
        aws_access_key_id=config["access_key"],
        aws_secret_access_key=config["secret_key"],
    )
    s3.download_file(config["bucket"], _R2_KEY, str(_LOCAL_CACHE))
    return _LOCAL_CACHE


def _read_master(regions: Sequence[str], *, force_refresh: bool) -> pd.DataFrame:
    path = ensure_master_table(force_refresh=force_refresh)
    with duckdb.connect(str(path), read_only=True) as conn:
        return conn.execute(
            "SELECT * FROM master WHERE region = ANY(?) ORDER BY region, bucket_ts",
            [list(regions)],
        ).df()


def load_energy_training_data_from_master(
    regions: Sequence[str],
    *,
    since: pd.Timestamp | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """`energy_data.load_energy_training_data`'s counterpart sourced from
    `master.duckdb` -- same output shape (`ts`/`region`/`demand_mw`/
    `price_mwh`/`total_generation_mw`/`total_renewable_mw`/5 generation
    buckets/weather columns), different data source. `master.duckdb` is
    on a uniform 30-minute grid across all 6 regions (`build_master_table.
    py`), so unlike the live marts this never mixes native cadences."""
    df = _read_master(regions, force_refresh=force_refresh)

    out = pd.DataFrame(
        {
            "ts": pd.to_datetime(df["bucket_ts"], utc=True),
            "region": df["region"],
            "demand_mw": pd.to_numeric(df["aemo_demand_mw"], errors="coerce"),
            "price_mwh": pd.to_numeric(df["aemo_price_mwh"], errors="coerce"),
            "total_generation_mw": pd.to_numeric(df["oe_total_generation_mw"], errors="coerce"),
            "total_renewable_mw": pd.to_numeric(df["oe_total_renewable_mw"], errors="coerce"),
            "temp_c": pd.to_numeric(df["temp_c"], errors="coerce"),
            "apparent_temp_c": pd.to_numeric(df["apparent_temp_c"], errors="coerce"),
            "humidity_pct": pd.to_numeric(df["humidity_pct"], errors="coerce"),
            "wind_speed_kmh": pd.to_numeric(df["wind_speed_kmh"], errors="coerce"),
            "wind_gust_kmh": pd.to_numeric(df["wind_gust_kmh"], errors="coerce"),
            "wind_direction_deg": pd.to_numeric(df["wind_direction_deg"], errors="coerce"),
            "cloud_oktas": pd.to_numeric(df["cloud_oktas"], errors="coerce"),
        }
    )

    # Generation-mix buckets: same canonical fuel-type grouping
    # `CarbonEngine` uses at inference time (`emission_factors.
    # GENERATION_BUCKET_FUEL_TYPES`), applied to `master.duckdb`'s
    # `oe_{fuel}_mw` columns -- every member column happens to follow
    # that exact naming convention already, confirmed against
    # `build_master_table.py`'s real output columns.
    for target_col in GENERATION_TARGET_COLUMNS:
        bucket = target_col.removesuffix("_mw")
        member_cols = [f"oe_{fuel}_mw" for fuel in GENERATION_BUCKET_FUEL_TYPES[bucket]]
        members = pd.concat(
            [pd.to_numeric(df[col], errors="coerce") for col in member_cols], axis=1
        )
        # `min_count=1` -- a single missing fuel within an otherwise-real
        # row is treated as "not dispatched" (0), but a row where *every*
        # member is NaN (OpenElectricity had no mix data at all for that
        # timestamp) stays NaN rather than becoming a fabricated "zero
        # generation" row -- same NaN semantics `demand_mw`/
        # `total_generation_mw` above already get, so
        # `EnergyForecastDataset`'s NaN-window drop excludes it correctly
        # instead of training on data that was never real.
        out[target_col] = members.sum(axis=1, min_count=1)

    if since is not None:
        out = out[out["ts"] >= since]

    return out.sort_values(["region", "ts"]).reset_index(drop=True)


def load_holidays_from_master(*, force_refresh: bool = False) -> pd.DataFrame:
    """`energy_data.load_holidays`'s counterpart sourced from
    `master.duckdb` -- same `(date, region)` shape."""
    path = ensure_master_table(force_refresh=force_refresh)
    with duckdb.connect(str(path), read_only=True) as conn:
        return conn.execute(
            "SELECT DISTINCT CAST(bucket_ts AS DATE) AS date, region "
            "FROM master WHERE holiday_name IS NOT NULL"
        ).df()
