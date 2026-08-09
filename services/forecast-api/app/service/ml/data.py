"""Warehouse queries backing both `/v1/forecast` inference/`/v1/emissions`/
`POST /v1/footprint` (the original, read-only half) and, as of the
training-code migration, real training-time dataset construction (the
`TimeSplit`/`fit_scalers`/`DemandDataset`/`TFTDataset`/`load_training_data`
section below, ported from `data-pipeline`'s identical `app.service.ml.
data` — this service trains now, not just serves).

`MARTS_SCHEMA`/`_TRAINING_COLUMNS` intentionally mirror `data-pipeline`'s
`app.service.ml.data` (same reasoning — `dbt`'s default schema-naming macro
puts `fct_energy_demand` in `raw_marts`, not a bare `marts` schema).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from torch import Tensor
from torch.utils.data import Dataset

from app.service.ml.features import FEATURE_COLUMNS, NUMERIC_COLUMNS, TARGET_COLUMN

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


async def _fetch_region_rows(db: AsyncSession, region: str, n_rows: int) -> pd.DataFrame:
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
    return df


async def load_latest_window(
    db: AsyncSession, region: str, n_rows: int, cross_regions: Sequence[str] = ()
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

    `cross_regions`: a real multi-region model's own trained region set
    (`bundle.feature_scalers.keys()`) -- when given, also fetches each of
    these OTHER regions' same-length latest windows, so `build_features`'s
    cross-region-context features (`total_demand_all_regions_mw`/
    `demand_share_of_total`) reflect the true multi-region total instead
    of "region vs. itself" (share=1.0). Real, measured need: a version
    trained across 5 regions together learns `demand_share_of_total` as a
    real per-region signal (TAS1 ~3% of NEM, NSW1 ~28%) -- serving it with
    this always pinned to 1.0 (this function's own prior single-region-
    only behavior) fed it a value far outside what training ever showed
    it, and live forecasts for the smaller regions (SA1/TAS1) came out
    inflated 3-6x as a result (root TODO.md's "NEM 5-region sum" item).
    The returned frame still has *all* fetched regions' rows -- the
    caller is responsible for filtering back down to just `region`'s
    rows after `build_features` runs, the same way training's own
    multi-region dataframe gets grouped by `region` throughout.

    Omitted (the default, `()`) reproduces the exact prior single-region
    behavior -- every other caller of this function is unaffected.
    """
    regions_to_fetch = list(dict.fromkeys([region, *cross_regions]))
    frames = [await _fetch_region_rows(db, r, n_rows) for r in regions_to_fetch]
    df = pd.concat(frames, ignore_index=True) if len(frames) > 1 else frames[0]
    return df.sort_values(["region", "ts"]).reset_index(drop=True)


async def load_holidays(db: AsyncSession) -> pd.DataFrame:
    result = await db.execute(text("SELECT date, region FROM raw.aemo_holidays"))
    return pd.DataFrame(result.mappings().all(), columns=("date", "region"))


# ════════════════════════════════════════════════════════════════════
# Training-time dataset construction (ported from data-pipeline's
# app.service.ml.data as part of the training-code migration -- this
# service trains now, not just serves. Everything below keeps D31's
# per-region discipline: a window, a fitted scaler, and a split
# boundary all respect region grouping the same way `add_lag_and_
# rolling` does, so nothing here accidentally undoes that.)
# ════════════════════════════════════════════════════════════════════


@dataclass
class TimeSplit:
    train: pd.DataFrame
    val: pd.DataFrame
    test: pd.DataFrame


def split_by_time(
    df: pd.DataFrame,
    ts_col: str = "ts",
    train_frac: float = 0.7,
    val_frac: float = 0.15,
) -> TimeSplit:
    """Chronological 70/15/15 split (default fractions) — not a random shuffle.

    A time-series model evaluated on a randomly shuffled split would be
    scored on interpolation, not the forecasting task it's actually built
    for (predicting *future* demand from *past* demand). The split point
    is chosen from `ts_col`'s sorted **unique** values and applied
    globally (not per-region), so every region's train/val/test boundary
    falls at the same timestamp — required for cross-region features
    (D31's `add_cross_region_context`) to mean the same thing in every
    split.
    """
    if not (0 < train_frac < 1) or not (0 < val_frac < 1) or train_frac + val_frac >= 1:
        raise ValueError("train_frac/val_frac must each be in (0, 1) and sum to < 1")

    unique_ts = np.sort(df[ts_col].unique())
    n = len(unique_ts)
    train_end = unique_ts[max(0, int(n * train_frac) - 1)]
    val_end = unique_ts[max(0, int(n * (train_frac + val_frac)) - 1)]

    train = df[df[ts_col] <= train_end]
    val = df[(df[ts_col] > train_end) & (df[ts_col] <= val_end)]
    test = df[df[ts_col] > val_end]
    return TimeSplit(train=train, val=val, test=test)


def fit_scalers(
    train: pd.DataFrame,
    group_col: str = "region",
    columns: Sequence[str] = NUMERIC_COLUMNS,
) -> dict[str, StandardScaler]:
    """One `StandardScaler` per region, fit on `train` only.

    Fitting on the full dataset (or on val/test) would leak those splits'
    distribution statistics into what's supposed to be an unseen-data
    evaluation. Rows with a `NaN` in any `columns` value (D31's
    lag/rolling warmup) are excluded from the fit — `StandardScaler`
    can't handle `NaN`, and warmup rows aren't representative of the
    steady-state distribution anyway. A region with no complete training
    rows gets no scaler and is silently skipped — the caller (via
    `apply_scalers`) is responsible for deciding what to do with it.
    """
    columns = list(columns)
    scalers: dict[str, StandardScaler] = {}
    for region, group in train.groupby(group_col):
        clean = group[columns].dropna()
        if clean.empty:
            continue
        scaler = StandardScaler()
        scaler.fit(clean.to_numpy())
        scalers[region] = scaler
    return scalers


def apply_scalers(
    df: pd.DataFrame,
    scalers: dict[str, StandardScaler],
    group_col: str = "region",
    columns: Sequence[str] = NUMERIC_COLUMNS,
) -> pd.DataFrame:
    """Apply each region's fitted scaler to `df`'s numeric columns.

    Rows for a region with no fitted scaler, or with a `NaN` in any
    `columns` value, are left unscaled — callers that need every row
    scaled should filter warmup rows and unscalable regions out first
    (`DemandDataset` already does the equivalent for windows).
    """
    out = df.copy()
    columns = list(columns)
    for region, scaler in scalers.items():
        mask = out[group_col] == region
        if not mask.any():
            continue
        values = out.loc[mask, columns]
        scalable = values.index[values.notna().all(axis=1)]
        if len(scalable) == 0:
            continue
        out.loc[scalable, columns] = scaler.transform(
            out.loc[scalable, columns].to_numpy()
        )
    return out


class DemandDataset(Dataset):
    """Sliding-window dataset over `build_features`'s output.

    Each sample is `lookback` past timesteps of `feature_columns` as
    input (`x`, shape `(lookback, n_features)`) and the next `horizon`
    timesteps of `target_col` as the target (`y`, shape `(horizon,)`).
    Windows are built one region at a time (sorted by `ts_col` within
    each region first) and never span two regions — a window straddling
    the boundary between NSW1's last rows and QLD1's first would mix two
    unrelated time series.

    Windows containing a `NaN` (D31's lag/rolling warmup, in either `x`
    or `y`) are dropped rather than imputed — silently filling warmup
    values would train the model on data it will never see at inference
    time, when a real window is always fully populated.

    All windows are materialized eagerly in `__init__`, trading memory
    for simplicity — fine at the data volumes this trains on (weeks to a
    few years of 5/30-minute interval data per region), not built to
    scale past that.
    """

    def __init__(
        self,
        df: pd.DataFrame,
        feature_columns: Sequence[str] = FEATURE_COLUMNS,
        target_col: str = TARGET_COLUMN,
        lookback: int = 48,
        horizon: int = 48,
        group_col: str = "region",
        ts_col: str = "ts",
    ) -> None:
        self.feature_columns = list(feature_columns)
        self.target_col = target_col
        self.lookback = lookback
        self.horizon = horizon

        self._samples: list[tuple[np.ndarray, np.ndarray]] = []
        sorted_df = df.sort_values([group_col, ts_col])
        window_span = lookback + horizon
        for _, group in sorted_df.groupby(group_col, sort=False):
            features = group[self.feature_columns].to_numpy(dtype=np.float32)
            target = group[self.target_col].to_numpy(dtype=np.float32)
            for start in range(len(group) - window_span + 1):
                x = features[start : start + lookback]
                y = target[start + lookback : start + window_span]
                if np.isnan(x).any() or np.isnan(y).any():
                    continue
                # pandas' `to_numpy()` can hand back a non-writable view
                # under copy-on-write -- `.copy()` here (once, at
                # construction) avoids torch's "non-writable tensor"
                # undefined-behavior warning on every `__getitem__`.
                self._samples.append((x.copy(), y.copy()))

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor]:
        x, y = self._samples[index]
        return torch.from_numpy(x), torch.from_numpy(y)


def collate(batch: Sequence[tuple[Tensor, Tensor]]) -> tuple[Tensor, Tensor]:
    """Stack `(x, y)` samples into batched tensors: `(batch, lookback, n_features)` / `(batch, horizon)`.

    `DataLoader`'s default `collate_fn` already does this correctly for
    equal-shaped tensors (every `DemandDataset` sample has the same
    shape) — this exists to make that batch shape explicit and importable
    by name, not because the default needed replacing.
    """
    xs, ys = zip(*batch, strict=True)
    return torch.stack(xs), torch.stack(ys)


class TFTDataset(Dataset):
    """Sliding-window dataset for `app.models.tft.DemandTFT`
    (`todo-model-training.md` Phase 2). Each sample is `(x_encoder,
    x_decoder, y)`:

    - `x_encoder`: `lookback` past timesteps of `encoder_columns`
      (`ml/features.py`'s `OBSERVED_PAST_COLUMNS + KNOWN_FUTURE_COLUMNS`
      by convention, though this class accepts any column list).
    - `x_decoder`: the next `horizon` timesteps of `decoder_columns`
      (`KNOWN_FUTURE_COLUMNS` by convention) — the real subset TFT's
      decoder is allowed to see for future timesteps.
    - `y`: the next `horizon` timesteps of `target_col`.

    Same per-region window discipline as `DemandDataset`: windows are
    built one region at a time and never span a region boundary; a
    window with a `NaN` anywhere in `x_encoder`/`x_decoder`/`y` is
    dropped, not imputed, for the same reason `DemandDataset` drops
    theirs (a real inference-time window is always fully populated).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        encoder_columns: Sequence[str],
        decoder_columns: Sequence[str],
        target_col: str = TARGET_COLUMN,
        lookback: int = 48,
        horizon: int = 48,
        group_col: str = "region",
        ts_col: str = "ts",
    ) -> None:
        self.encoder_columns = list(encoder_columns)
        self.decoder_columns = list(decoder_columns)
        self.target_col = target_col
        self.lookback = lookback
        self.horizon = horizon

        self._samples: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        sorted_df = df.sort_values([group_col, ts_col])
        window_span = lookback + horizon
        for _, group in sorted_df.groupby(group_col, sort=False):
            encoder_features = group[self.encoder_columns].to_numpy(dtype=np.float32)
            decoder_features = group[self.decoder_columns].to_numpy(dtype=np.float32)
            target = group[self.target_col].to_numpy(dtype=np.float32)
            for start in range(len(group) - window_span + 1):
                x_enc = encoder_features[start : start + lookback]
                x_dec = decoder_features[start + lookback : start + window_span]
                y = target[start + lookback : start + window_span]
                if np.isnan(x_enc).any() or np.isnan(x_dec).any() or np.isnan(y).any():
                    continue
                self._samples.append((x_enc.copy(), x_dec.copy(), y.copy()))

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor, Tensor]:
        x_enc, x_dec, y = self._samples[index]
        return torch.from_numpy(x_enc), torch.from_numpy(x_dec), torch.from_numpy(y)


def collate_tft(
    batch: Sequence[tuple[Tensor, Tensor, Tensor]],
) -> tuple[Tensor, Tensor, Tensor]:
    """`TFTDataset`'s counterpart to `collate` -- stacks `(x_encoder,
    x_decoder, y)` samples into batched tensors."""
    x_encs, x_decs, ys = zip(*batch, strict=True)
    return torch.stack(x_encs), torch.stack(x_decs), torch.stack(ys)


async def load_training_data(
    db: AsyncSession, regions: Sequence[str], since: pd.Timestamp | None = None
) -> pd.DataFrame:
    """ECO-D35: the dbt-materialized counterpart to `ml/features.py`'s
    module docstring's "expected input contract" — queries
    `{MARTS_SCHEMA}.fct_energy_demand` (built by
    `dbt/ecolens/models/intermediate/int_demand_with_weather.sql`, table-
    materialized via `fct_energy_demand.sql`) for exactly the columns
    `build_features` needs, long-form (one row per `(ts, region)`).

    The model never trains against a live query beyond this one read —
    `ml/train.py` snapshots the result into memory (matching `README.md`'s
    "the model never trains on a live Postgres connection", minus the
    Parquet-on-S3 detail: this snapshots in-process, not to a separate
    artifact store — see `ml/train.py`'s own docstring for that
    simplification).
    """
    where = ["region = ANY(:regions)"]
    params: dict[str, object] = {"regions": list(regions)}
    if since is not None:
        where.append("ts >= :since")
        params["since"] = since

    result = await db.execute(
        text(
            # nosec B608 -- `_TRAINING_COLUMNS`/`MARTS_SCHEMA` are fixed
            # module-level constants and `where` is only ever built from
            # fixed literal clause fragments above; values are bound params
            f"SELECT {', '.join(_TRAINING_COLUMNS)} "  # nosec B608
            f"FROM {MARTS_SCHEMA}.fct_energy_demand "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY region, ts"
        ),
        params,
    )
    df = pd.DataFrame(result.mappings().all(), columns=_TRAINING_COLUMNS)
    # asyncpg hands back Postgres `numeric` columns as `decimal.Decimal`,
    # not `float` -- every arithmetic op downstream (`ml.features`, this
    # module's own scalers) is written against plain floats, and Decimal
    # doesn't mix with float in arithmetic (`TypeError: unsupported
    # operand type(s) for -: 'float' and 'decimal.Decimal'`). Cast once,
    # here, rather than defensively in every function that touches these
    # columns downstream.
    df[list(_NUMERIC_TRAINING_COLUMNS)] = df[list(_NUMERIC_TRAINING_COLUMNS)].apply(
        pd.to_numeric
    )
    return df


# `ml.ml_features_demand_v1` -- an orphaned table found live in the
# warehouse (no dbt model, no pipeline code, no git history references it
# anywhere in this repo) that happens to cover a full year across all 6
# real regions (103,734 rows total) versus `load_training_data`'s
# dbt-tracked `fct_energy_demand` (~55K rows, ~4 months of history since
# WEM/NEM only started landing recently). Real caveat, confirmed by direct
# query before this was wired in: 66% of its rows
# (`data_quality_status='imputed'`) are gap-filled/synthetic, not real
# observations -- see `load_ml_features_v1_imputed_fraction`.
_ML_FEATURES_V1_SCHEMA = "ml"
_ML_FEATURES_V1_TABLE = "ml_features_demand_v1"


async def load_ml_features_v1_training_data(
    db: AsyncSession, regions: Sequence[str], since: pd.Timestamp | None = None
) -> pd.DataFrame:
    """Alternate raw-data source to `load_training_data`, same output
    shape (`_TRAINING_COLUMNS`) and same downstream contract --
    deliberately selects only `ml_features_demand_v1`'s *raw* columns,
    not its own precomputed `demand_lag_*`/`*_sin`/`*_cos` columns, so
    `build_features` re-derives lags/rolling stats/cyclical encodings
    itself, identically to the production path. That keeps a model
    trained on this source feature-contract-compatible with
    `forecast-api`'s serving-time feature construction, which only knows
    the production contract, not this table's bespoke columns.
    `renewable_generation_mw` is renamed to `total_renewable_mw` here to
    match `_TRAINING_COLUMNS` -- same real signal, different name in this
    table.
    """
    where = ["region = ANY(:regions)"]
    params: dict[str, object] = {"regions": list(regions)}
    if since is not None:
        where.append("ts >= :since")
        params["since"] = since

    result = await db.execute(
        text(
            # nosec B608 -- fixed module-level constants + fixed literal
            # clause fragments only; values are bound params (same
            # pattern as `load_training_data` above)
            "SELECT ts, region, demand_mw, price_mwh, total_generation_mw, "  # nosec B608
            "renewable_generation_mw AS total_renewable_mw, temp_c, "
            "apparent_temp_c, humidity_pct, wind_speed_kmh "
            f"FROM {_ML_FEATURES_V1_SCHEMA}.{_ML_FEATURES_V1_TABLE} "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY region, ts"
        ),
        params,
    )
    df = pd.DataFrame(result.mappings().all(), columns=_TRAINING_COLUMNS)
    df[list(_NUMERIC_TRAINING_COLUMNS)] = df[list(_NUMERIC_TRAINING_COLUMNS)].apply(
        pd.to_numeric
    )
    return df


async def load_ml_features_v1_imputed_fraction(
    db: AsyncSession, regions: Sequence[str]
) -> float:
    """Real `data_quality_status='imputed'` fraction for `regions` in
    `ml.ml_features_demand_v1` -- logged as an MLflow param by any run
    trained from that source (`ml.tune.tune_optuna`'s `data_source`
    option), so the imputation ratio is visible on the run itself, not
    just in whatever investigation first found it. `0.0` (not an error)
    when `regions` has no rows at all -- an empty-data problem is
    already reported elsewhere (the caller's own `raw_df.empty` check)."""
    result = await db.execute(
        text(
            "SELECT count(*) FILTER (WHERE data_quality_status = 'imputed')::float "
            "/ NULLIF(count(*), 0) AS frac "
            f"FROM {_ML_FEATURES_V1_SCHEMA}.{_ML_FEATURES_V1_TABLE} "  # nosec B608
            "WHERE region = ANY(:regions)"
        ),
        {"regions": list(regions)},
    )
    row = result.mappings().first()
    frac = row["frac"] if row else None
    return float(frac) if frac is not None else 0.0


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


async def load_emissions_trace(
    db: AsyncSession, region: str, limit: int
) -> tuple[list[dict], dict[object, list[dict]]]:
    """The most recent `limit` hours of `fct_carbon_intensity` for
    `region`, plus the `fct_generation_mix` per-fuel rows that sum into
    each of those same hours — backs `GET /v1/emissions/trace`. Two
    queries rather than one join: the aggregate table is one row per
    hour, the per-fuel table is many rows per hour, and fetching the
    per-fuel rows only for the exact hour set the first query actually
    returned (not a separate `[start, end]` window recomputed
    independently) guarantees the two can never disagree about which
    hours are in scope.

    Returns `(intensity_rows, mix_rows_by_hour)` — `mix_rows_by_hour`
    keyed by the same `hour` value `intensity_rows` uses, so the route
    layer can zip them together without a third query.
    """
    intensity_result = await db.execute(
        text(
            "SELECT hour, total_generation_mwh, total_emissions_kgco2e, "  # nosec B608 -- `MARTS_SCHEMA` is a fixed module-level constant, not user input
            "intensity_kgco2e_per_mwh, factors_version "
            f"FROM {MARTS_SCHEMA}.fct_carbon_intensity "
            "WHERE region = :region ORDER BY hour DESC LIMIT :limit"
        ),
        {"region": region, "limit": limit},
    )
    intensity_rows = [dict(row) for row in intensity_result.mappings().all()]
    if not intensity_rows:
        return [], {}

    hours = [row["hour"] for row in intensity_rows]
    # `[min(hours), max(hours)]` rather than an exact `IN`/`= ANY` set --
    # `intensity_rows` is already exactly the N most recent hours for
    # this region with no gaps skipped, so a plain range covers the
    # identical hour set without needing array-parameter binding at all.
    mix_result = await db.execute(
        text(
            "SELECT hour, fuel_type, total_generation_mwh, total_emissions_kgco2e "  # nosec B608 -- `MARTS_SCHEMA` is a fixed module-level constant, not user input
            f"FROM {MARTS_SCHEMA}.fct_generation_mix "
            "WHERE region = :region AND hour >= :min_hour AND hour <= :max_hour "
            "ORDER BY hour DESC, total_emissions_kgco2e DESC NULLS LAST"
        ),
        {"region": region, "min_hour": min(hours), "max_hour": max(hours)},
    )
    mix_rows_by_hour: dict[object, list[dict]] = {}
    for row in mix_result.mappings().all():
        mix_rows_by_hour.setdefault(row["hour"], []).append(dict(row))

    return intensity_rows, mix_rows_by_hour


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
