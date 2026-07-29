"""Training-set loader for `model/fuel_ensemble.py` -- the per-fuel
counterpart to `training_data.py`'s `TrainingSetLoader`.

`ml_features_demand_v1` (what `TrainingSetLoader` reads) carries the
demand-forecasting `FEATURE_COLUMNS` covariates but not the 16 per-fuel MW
breakdown -- those live on `fact_generation_30min` instead (see
`model/fuel_ensemble.py`'s docstring). Rather than duplicate the
covariate-engineering work `ml_features_demand_v1` already does (lags,
rolling stats, cyclical encodings), this loader joins the two marts on
`(region, ts_30)`: `FEATURE_COLUMNS` from `ml_features_demand_v1`,
`FUEL_COLUMNS` targets from `fact_generation_30min`.
"""

from __future__ import annotations

from datetime import date, datetime

import asyncpg
import pandas as pd

from ecolens.config import Settings, get_settings
from ecolens.shared.observability.logging import get_logger
from ecolens.warehouse.core.api_settings import (
    WarehouseApiSettings,
    get_warehouse_api_settings,
)

from ecolens.forecasting.model.fuel_ensemble import FUEL_COLUMNS
from ecolens.forecasting.schema.features import FEATURE_COLUMNS

log = get_logger(__name__)

_SELECT_COLUMNS = ", ".join(
    [f"f.{c}" for c in FEATURE_COLUMNS] + [f"g.{c}" for c in FUEL_COLUMNS]
)
_QUERY = (
    f"select f.region, f.ts_30, {_SELECT_COLUMNS} "
    "from ml_features_demand_v1 f "
    "join fact_generation_30min g on g.region = f.region and g.ts_30 = f.ts_30 "
    "{where} "
    "order by f.region, f.ts_30"
)


class FuelTrainingSetLoader:
    """Reads the joined `ml_features_demand_v1` x `fact_generation_30min`
    feature/target table for `training/train_fuel_ensemble.py`.
    """

    def __init__(
        self,
        warehouse_settings: WarehouseApiSettings | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.warehouse_settings = warehouse_settings or get_warehouse_api_settings()
        self.settings = settings or get_settings()

    async def fetch(
        self,
        regions: tuple[str, ...] | None = None,
        *,
        since: date | datetime | None = None,
        until: date | datetime | None = None,
    ) -> pd.DataFrame:
        """Same `[since, until)`/`regions` scoping as
        `TrainingSetLoader.fetch` -- see that method's docstring.
        """
        ws = self.warehouse_settings
        if ws.pg_dsn:
            conn = await asyncpg.connect(
                dsn=ws.pg_dsn, timeout=ws.pg_command_timeout_seconds
            )
        else:
            conn = await asyncpg.connect(
                host=ws.pg_host,
                port=ws.pg_port,
                database=ws.pg_database,
                user=ws.pg_user,
                password=ws.pg_password,
                timeout=ws.pg_command_timeout_seconds,
            )
        try:
            clauses = []
            params: list[object] = []
            if regions:
                params.append(list(regions))
                clauses.append(f"f.region = any(${len(params)}::text[])")
            if since is not None:
                params.append(since)
                clauses.append(f"f.ts_30 >= ${len(params)}")
            if until is not None:
                params.append(until)
                clauses.append(f"f.ts_30 < ${len(params)}")
            where = f"where {' and '.join(clauses)}" if clauses else ""
            query = _QUERY.format(where=where)
            rows = await conn.fetch(query, *params)
        finally:
            await conn.close()

        log.info(
            "fuel_training.fetched",
            rows=len(rows),
            regions=regions,
            since=since.isoformat() if since else None,
            until=until.isoformat() if until else None,
        )
        return pd.DataFrame(dict(r) for r in rows)


__all__ = ["FuelTrainingSetLoader"]
