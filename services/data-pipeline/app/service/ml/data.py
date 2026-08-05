"""Dataset construction for the demand-forecasting model (ECO-D32).

Consumes `app.service.ml.features.build_features`'s output — one row per
`(ts, region)`, `FEATURE_COLUMNS` + `TARGET_COLUMN` — and turns it into
sliding-window PyTorch samples. Everything here keeps D31's per-region
discipline: a window, a fitted scaler, and a split boundary all respect
region grouping the same way `add_lag_and_rolling` does, so nothing here
accidentally undoes that.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
import torch
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from torch import Tensor
from torch.utils.data import Dataset

from app.service.ml.features import FEATURE_COLUMNS, NUMERIC_COLUMNS, TARGET_COLUMN

# dbt's built-in `generate_schema_name` macro (no override in
# `dbt/ecolens/macros/` -- see `dbt_project.yml`'s materialization
# comment) names a custom-schema model `<profile_schema>_<custom_schema>`;
# `profiles.yml`'s `schema: "raw"` + `dbt_project.yml`'s marts
# `+schema: marts` means `fct_energy_demand` actually lands in
# `raw_marts`, not a bare `marts` schema.
MARTS_SCHEMA = "raw_marts"


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


async def load_holidays(db: AsyncSession) -> pd.DataFrame:
    """`raw.aemo_holidays`, shaped for `ml.features.add_calendar_features`'s
    `holidays` parameter (`date`, `region`)."""
    result = await db.execute(text("SELECT date, region FROM raw.aemo_holidays"))
    return pd.DataFrame(result.mappings().all(), columns=("date", "region"))


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
