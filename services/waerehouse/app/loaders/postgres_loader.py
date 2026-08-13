"""Bulk-load a staged DataFrame into Postgres `raw.*` (README Phase 2's
"DuckDB-to-PostgreSQL Transfer Logic" + "Idempotent Load Handling").

Ported from `data-pipeline`'s `pipeline.landing.load_to_postgres` — the
exact same COPY-into-temp-table + `INSERT ... ON CONFLICT DO NOTHING`
mechanism, now living in the service that's actually supposed to own
this responsibility going forward. Not a rewrite: same approach, same
reasoning, just relocated.
"""

from __future__ import annotations

import io
import uuid

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

# Postgres COPY's own CSV-format default null representation is an
# unquoted empty string -- indistinguishable from a genuine empty-string
# value in a text column. `\N` (the TEXT-format convention) instead, on
# both the pandas and asyncpg sides, disambiguates "this was NULL" from
# "this was an empty string" (same choice data-pipeline's identical
# loader makes).
_NULL_MARKER = r"\N"


async def load_to_postgres(
    session: AsyncSession, df: pd.DataFrame, table: str, schema: str = "raw"
) -> int:
    """Bulk-load `df` into `schema.table` via asyncpg's COPY (CSV format).

    Ingestion is expected to be safely re-runnable (overlapping
    `lookback_minutes` windows re-fetch rows already landed, a
    redelivered RabbitMQ message re-triggers this handler for the same
    run), so a plain COPY straight into the target table isn't good
    enough -- it dies on the first row that collides with an existing
    natural-key `PRIMARY KEY`. COPY instead into a throwaway temp table
    (still fast, still COPY), then `INSERT ... ON CONFLICT DO NOTHING`
    from there into the real table (README Phase 2's "deduplication and
    upsert mechanisms... using natural keys") -- rows already landed by
    an earlier run are silently skipped, the natural key itself (`ts` +
    region/station/fuel_type, per table's own `PRIMARY KEY`) *is* the
    dedup key.

    Returns the number of rows actually inserted (excluding skipped
    duplicates). A no-op (returns 0) for an empty DataFrame, without
    opening a connection.
    """
    if df.empty:
        return 0

    raw_connection = await session.connection()
    driver_connection = (await raw_connection.get_raw_connection()).driver_connection
    if driver_connection is None:
        raise RuntimeError("no underlying asyncpg connection")

    columns = list(df.columns)
    csv_text = df.to_csv(index=False, header=False, na_rep=_NULL_MARKER)
    buffer = io.BytesIO(csv_text.encode("utf-8"))

    staging_table = f"_load_{uuid.uuid4().hex[:12]}"
    quoted_columns = ", ".join(f'"{c}"' for c in columns)

    # A bare `driver_connection.execute()` auto-commits as its own
    # transaction -- `ON COMMIT DROP` would drop the staging table before
    # `copy_to_table` ever saw it. One explicit transaction keeps
    # create/copy/insert on the same server-side session.
    # `schema`/`table` come only from this module's own caller
    # (`consumers.landed_events`), always a literal registry table name
    # sourced from the RabbitMQ payload's own `table` field -- never
    # request input -- and `staging_table`/`quoted_columns` are generated
    # here, not passed in. Postgres identifiers can't be bound params, so
    # this has to be string-built; nosec B608 applies to all three
    # statements below.
    async with driver_connection.transaction():
        await driver_connection.execute(
            f'CREATE TEMP TABLE "{staging_table}" '  # nosec B608
            f'(LIKE "{schema}"."{table}" INCLUDING DEFAULTS) ON COMMIT DROP'
        )
        await driver_connection.copy_to_table(
            staging_table,
            source=buffer,
            columns=columns,
            format="csv",
            null=_NULL_MARKER,
        )
        result = await driver_connection.execute(
            f'INSERT INTO "{schema}"."{table}" ({quoted_columns}) '  # nosec B608
            f'SELECT {quoted_columns} FROM "{staging_table}" '
            "ON CONFLICT DO NOTHING"
        )
    return int(result.split()[-1])
