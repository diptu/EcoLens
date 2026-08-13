"""`data.load_latest_window`'s counterpart for `EnergyForecastLSTM` --
same query shape, wider column set (`_ENERGY_TRAINING_COLUMNS`, kept in
sync by hand with `data-pipeline`'s `service/ml/energy_data.py`, same
cross-service duplication reasoning as `models/energy_forecast_lstm.py`'s
own docstring).

`load_energy_training_data`/`EnergyForecastDataset`/`collate_energy`
below (added alongside the training-code migration -- this service
trains the multi-task model now, not just serves it) were ported
verbatim from data-pipeline's identical module.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pandas as pd
import torch
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from torch import Tensor
from torch.utils.data import Dataset

from app.service.ml.data import MARTS_SCHEMA
from app.service.ml.energy_features import DEMAND_TARGET_COLUMN, FEATURE_COLUMNS, GENERATION_TARGET_COLUMNS

_ENERGY_TRAINING_COLUMNS: tuple[str, ...] = (
    "ts",
    "region",
    "demand_mw",
    "price_mwh",
    "total_generation_mw",
    "total_renewable_mw",
    "coal_mw",
    "gas_mw",
    "wind_mw",
    "solar_mw",
    "other_mw",
    "temp_c",
    "apparent_temp_c",
    "humidity_pct",
    "wind_speed_kmh",
    "wind_gust_kmh",
    "wind_direction_deg",
    "cloud_oktas",
)
_NUMERIC_ENERGY_TRAINING_COLUMNS = tuple(c for c in _ENERGY_TRAINING_COLUMNS if c not in ("ts", "region"))


async def load_latest_energy_window(db: AsyncSession, region: str, n_rows: int) -> pd.DataFrame:
    """The most recent `n_rows` rows for `region`, ascending by `ts` --
    same shape/reasoning as `data.load_latest_window`, just
    `_ENERGY_TRAINING_COLUMNS` wide."""
    result = await db.execute(
        text(
            # nosec B608 -- fixed module-level constants, not user input
            f"SELECT {', '.join(_ENERGY_TRAINING_COLUMNS)} "  # nosec B608
            f"FROM {MARTS_SCHEMA}.fct_energy_demand "
            "WHERE region = :region ORDER BY ts DESC LIMIT :n_rows"
        ),
        {"region": region, "n_rows": n_rows},
    )
    rows = result.mappings().all()
    df = pd.DataFrame(rows, columns=_ENERGY_TRAINING_COLUMNS)
    df[list(_NUMERIC_ENERGY_TRAINING_COLUMNS)] = df[list(_NUMERIC_ENERGY_TRAINING_COLUMNS)].apply(pd.to_numeric)
    return df.sort_values("ts").reset_index(drop=True)


async def load_energy_training_data(
    db: AsyncSession, regions: Sequence[str], since: pd.Timestamp | None = None
) -> pd.DataFrame:
    """`ml/data.load_training_data`'s counterpart for
    `EnergyForecastLSTM` -- same query shape against the same
    `{MARTS_SCHEMA}.fct_energy_demand`, just `_ENERGY_TRAINING_COLUMNS`
    wide instead of `_TRAINING_COLUMNS`."""
    where = ["region = ANY(:regions)"]
    params: dict[str, object] = {"regions": list(regions)}
    if since is not None:
        where.append("ts >= :since")
        params["since"] = since

    result = await db.execute(
        text(
            # nosec B608 -- `_ENERGY_TRAINING_COLUMNS`/`MARTS_SCHEMA` are
            # fixed module-level constants and `where` is only ever built
            # from fixed literal clause fragments above; values are bound
            # params.
            f"SELECT {', '.join(_ENERGY_TRAINING_COLUMNS)} "  # nosec B608
            f"FROM {MARTS_SCHEMA}.fct_energy_demand "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY region, ts"
        ),
        params,
    )
    df = pd.DataFrame(result.mappings().all(), columns=_ENERGY_TRAINING_COLUMNS)
    # Same Decimal->float cast `load_training_data` does, same reason
    # (asyncpg hands back Postgres `numeric` as `decimal.Decimal`).
    df[list(_NUMERIC_ENERGY_TRAINING_COLUMNS)] = df[list(_NUMERIC_ENERGY_TRAINING_COLUMNS)].apply(pd.to_numeric)
    return df


class EnergyForecastDataset(Dataset):
    """Each sample: `x` (`lookback` past timesteps of `feature_columns`,
    `(lookback, n_features)`), `demand_y` (next `horizon` timesteps of
    `demand_target_col`, `(horizon,)`), `generation_y` (next `horizon`
    timesteps of `generation_target_cols`, `(horizon, len(generation_target_cols))`).
    """

    def __init__(
        self,
        df: pd.DataFrame,
        feature_columns: Sequence[str] = FEATURE_COLUMNS,
        demand_target_col: str = DEMAND_TARGET_COLUMN,
        generation_target_cols: Sequence[str] = GENERATION_TARGET_COLUMNS,
        lookback: int = 336,
        horizon: int = 48,
        group_col: str = "region",
        ts_col: str = "ts",
    ) -> None:
        self.feature_columns = list(feature_columns)
        self.demand_target_col = demand_target_col
        self.generation_target_cols = list(generation_target_cols)
        self.lookback = lookback
        self.horizon = horizon

        self._samples: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        sorted_df = df.sort_values([group_col, ts_col])
        window_span = lookback + horizon
        for _, group in sorted_df.groupby(group_col, sort=False):
            features = group[self.feature_columns].to_numpy(dtype=np.float32)
            demand_target = group[self.demand_target_col].to_numpy(dtype=np.float32)
            generation_target = group[self.generation_target_cols].to_numpy(dtype=np.float32)
            for start in range(len(group) - window_span + 1):
                x = features[start : start + lookback]
                demand_y = demand_target[start + lookback : start + window_span]
                generation_y = generation_target[start + lookback : start + window_span]
                if np.isnan(x).any() or np.isnan(demand_y).any() or np.isnan(generation_y).any():
                    continue
                self._samples.append((x.copy(), demand_y.copy(), generation_y.copy()))

    def __len__(self) -> int:
        return len(self._samples)

    def __getitem__(self, index: int) -> tuple[Tensor, Tensor, Tensor]:
        x, demand_y, generation_y = self._samples[index]
        return torch.from_numpy(x), torch.from_numpy(demand_y), torch.from_numpy(generation_y)


def collate_energy(batch: Sequence[tuple[Tensor, Tensor, Tensor]]) -> tuple[Tensor, Tensor, Tensor]:
    """`EnergyForecastDataset`'s counterpart to `ml/data.collate`/
    `collate_tft` -- stacks `(x, demand_y, generation_y)` samples into
    batched tensors."""
    xs, demand_ys, generation_ys = zip(*batch, strict=True)
    return torch.stack(xs), torch.stack(demand_ys), torch.stack(generation_ys)
