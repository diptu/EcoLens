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
