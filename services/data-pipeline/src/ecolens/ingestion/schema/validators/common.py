"""Shared post-processing for the per-source pandera validators.

`pd.DataFrame(docs).to_dict("records")` can turn a `None` in an
optional, pandera-undeclared column (e.g. holidays' `observed_date`)
into a bare Python `float('nan')` once a batch mixes `None` with real
values -- confirmed empirically across pandas' object/string-dtype
handling, not something `.where(df.notna(), None)` reliably undoes.
Cleaning the record list directly, after `to_dict()`, sidesteps that
dtype-inference entirely. Matters beyond the obvious "wrong value": a
stray NaN written to MongoDB and synced to Postgres later contaminates
dbt/SQL aggregates (`avg()` over a NaN is NaN), not just this one field.
"""

from __future__ import annotations

import math
from typing import Any


def clean_nan(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace bare `float('nan')` values with `None`, in place."""
    for record in records:
        for key, value in record.items():
            if isinstance(value, float) and math.isnan(value):
                record[key] = None
    return records


__all__ = ["clean_nan"]
