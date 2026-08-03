"""Schema drift detection for the 5 `raw.*` tables — backs
`GET /v1/data-quality/schema` (API_SPECEFICATIONS.md §3.4).

Compares each table's *live* columns (`information_schema.columns`,
queried against whatever Postgres this process is actually connected to)
against `_EXPECTED_COLUMNS` — a hand-maintained snapshot of what
`migrations/0011_reconcile_ingest_schema.sql` actually declared, matching
`docs/data/ingestion-schema.md`'s own column reference. There's no
separate "schema registry" service this compares against; the
migrations *are* the source of truth, and this dict has to be updated by
hand alongside them if a raw table's schema ever changes on purpose --
same maintenance burden the migrations/docs pairing already documents
("If you change one, change the other").

`detect_drift` reconciles `meta.schema_drifts` on every call: drifts
still present get their `last_checked_at` bumped (first_seen_at stays
fixed), drifts no longer present (schema reverted, or the gap got closed
by an actual migration) get deleted.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# table_name -> {column_name: (postgres_data_type, is_nullable)}. Types
# are exactly what `information_schema.columns.data_type` reports for
# each DDL type migrations 0002-0011 used.
_EXPECTED_COLUMNS: dict[str, dict[str, tuple[str, str]]] = {
    "aemo_nem_dispatch": {
        "ts": ("timestamp with time zone", "NO"),
        "region": ("text", "NO"),
        "demand_mw": ("numeric", "YES"),
        "price_mwh": ("numeric", "YES"),
        "coal_mw": ("numeric", "YES"),
        "gas_mw": ("numeric", "YES"),
        "hydro_mw": ("numeric", "YES"),
        "wind_mw": ("numeric", "YES"),
        "solar_utility_mw": ("numeric", "YES"),
        "solar_rooftop_mw": ("numeric", "YES"),
        "battery_mw": ("numeric", "YES"),
        "net_import_mw": ("numeric", "YES"),
        "source": ("text", "YES"),
        "ingested_at": ("timestamp with time zone", "NO"),
        "ingest_run_id": ("uuid", "YES"),
    },
    "aemo_wem_dispatch": {
        "ts": ("timestamp with time zone", "NO"),
        "region": ("text", "NO"),
        "demand_mw": ("numeric", "YES"),
        "price_mwh": ("numeric", "YES"),
        "coal_mw": ("numeric", "YES"),
        "gas_mw": ("numeric", "YES"),
        "diesel_mw": ("numeric", "YES"),
        "wind_mw": ("numeric", "YES"),
        "solar_utility_mw": ("numeric", "YES"),
        "solar_rooftop_mw": ("numeric", "YES"),
        "battery_mw": ("numeric", "YES"),
        "biomass_mw": ("numeric", "YES"),
        "total_generation_mw": ("numeric", "YES"),
        "source": ("text", "YES"),
        "ingested_at": ("timestamp with time zone", "NO"),
        "ingest_run_id": ("uuid", "YES"),
    },
    "bom_observations": {
        "ts": ("timestamp with time zone", "NO"),
        "station_id": ("text", "NO"),
        "region": ("text", "NO"),
        "temp_c": ("numeric", "YES"),
        "apparent_temp_c": ("numeric", "YES"),
        "dew_point_c": ("numeric", "YES"),
        "humidity_pct": ("numeric", "YES"),
        "wind_speed_kmh": ("numeric", "YES"),
        "wind_direction_deg": ("numeric", "YES"),
        "wind_gust_kmh": ("numeric", "YES"),
        "pressure_hpa": ("numeric", "YES"),
        "rain_since_9am_mm": ("numeric", "YES"),
        "cloud_oktas": ("numeric", "YES"),
        "source": ("text", "YES"),
        "ingested_at": ("timestamp with time zone", "NO"),
        "ingest_run_id": ("uuid", "YES"),
    },
    "openelectricity_mix": {
        "ts": ("timestamp with time zone", "NO"),
        "network_code": ("text", "NO"),
        "region": ("text", "NO"),
        "coal_mw": ("numeric", "YES"),
        "gas_mw": ("numeric", "YES"),
        "hydro_mw": ("numeric", "YES"),
        "wind_mw": ("numeric", "YES"),
        "solar_utility_mw": ("numeric", "YES"),
        "solar_rooftop_mw": ("numeric", "YES"),
        "battery_discharge_mw": ("numeric", "YES"),
        "battery_charge_mw": ("numeric", "YES"),
        "pumped_hydro_mw": ("numeric", "YES"),
        "biomass_mw": ("numeric", "YES"),
        "distillate_mw": ("numeric", "YES"),
        "total_generation_mw": ("numeric", "YES"),
        "total_renewable_mw": ("numeric", "YES"),
        "demand_mw": ("numeric", "YES"),
        "price_mwh": ("numeric", "YES"),
        "intensity_kg_per_mwh": ("numeric", "YES"),
        "source": ("text", "YES"),
        "ingested_at": ("timestamp with time zone", "NO"),
        "ingest_run_id": ("uuid", "YES"),
    },
    "aemo_holidays": {
        "date": ("date", "NO"),
        "region": ("text", "NO"),
        "holiday_name": ("text", "NO"),
        "is_workday": ("boolean", "NO"),
        "source": ("text", "YES"),
        "ingested_at": ("timestamp with time zone", "NO"),
        "ingest_run_id": ("uuid", "YES"),
    },
}

# table_name -> registry.py's `IngestSource.source` value, for the
# `source_id`/`source` fields on each reported drift.
_TABLE_SOURCE: dict[str, str] = {
    "aemo_nem_dispatch": "aemo_nem",
    "aemo_wem_dispatch": "aemo_wem",
    "bom_observations": "bom",
    "openelectricity_mix": "openelectricity",
    "aemo_holidays": "aemo_holidays",
}

# A type change is "safe"/auto-adapted if it's a widening conversion no
# existing query would break on (e.g. int4 -> numeric can hold everything
# int4 could); anything else needs a human to look at it.
_SAFE_TYPE_WIDENING = {
    ("integer", "numeric"),
    ("integer", "bigint"),
    ("integer", "double precision"),
    ("real", "double precision"),
    ("character varying", "text"),
}


async def _live_columns(
    db: AsyncSession, table_name: str
) -> dict[str, tuple[str, str]]:
    result = await db.execute(
        text(
            "SELECT column_name, data_type, is_nullable "
            "FROM information_schema.columns "
            "WHERE table_schema = 'raw' AND table_name = :table_name"
        ),
        {"table_name": table_name},
    )
    return {
        row["column_name"]: (row["data_type"], row["is_nullable"])
        for row in result.mappings().all()
    }


def _diff_table(
    table_name: str, live: dict[str, tuple[str, str]]
) -> list[dict[str, Any]]:
    expected = _EXPECTED_COLUMNS[table_name]
    source = _TABLE_SOURCE[table_name]
    drifts: list[dict[str, Any]] = []

    for column, (expected_type, _) in expected.items():
        if column not in live:
            drifts.append(
                {
                    "source": source,
                    "table_name": f"raw.{table_name}",
                    "column_name": column,
                    "kind": "column_removed",
                    "old_type": expected_type,
                    "new_type": None,
                    "severity": "high",
                    "auto_adapted": False,
                    "action_required": True,
                    "downstream_impact": "Queries/dbt models selecting this column will error.",
                }
            )

    for column, (live_type, live_nullable) in live.items():
        expected_entry = expected.get(column)
        if expected_entry is None:
            drifts.append(
                {
                    "source": source,
                    "table_name": f"raw.{table_name}",
                    "column_name": column,
                    "kind": "column_added",
                    "old_type": None,
                    "new_type": live_type,
                    "severity": "low",
                    "auto_adapted": True,
                    "action_required": False,
                    "downstream_impact": None,
                }
            )
            continue

        expected_type, expected_nullable = expected_entry
        if live_type != expected_type:
            safe = (expected_type, live_type) in _SAFE_TYPE_WIDENING
            drifts.append(
                {
                    "source": source,
                    "table_name": f"raw.{table_name}",
                    "column_name": column,
                    "kind": "type_changed",
                    "old_type": expected_type,
                    "new_type": live_type,
                    "severity": "medium" if safe else "high",
                    "auto_adapted": safe,
                    "action_required": not safe,
                    "downstream_impact": None
                    if safe
                    else "dbt staging models may fail to compile/run against this column.",
                }
            )
        if live_nullable != expected_nullable:
            drifts.append(
                {
                    "source": source,
                    "table_name": f"raw.{table_name}",
                    "column_name": column,
                    "kind": "nullable_changed",
                    "old_type": expected_nullable,
                    "new_type": live_nullable,
                    "severity": "low",
                    "auto_adapted": True,
                    "action_required": False,
                    "downstream_impact": None,
                }
            )

    return drifts


async def detect_drift(db: AsyncSession) -> list[dict[str, Any]]:
    """Detect drift on all 5 `raw.*` tables and reconcile it into
    `meta.schema_drifts` (upsert what's still present, delete what's no
    longer detected). Returns the full current drift list."""
    all_drifts: list[dict[str, Any]] = []
    for table_name in _EXPECTED_COLUMNS:
        live = await _live_columns(db, table_name)
        all_drifts.extend(_diff_table(table_name, live))

    for table_name in _EXPECTED_COLUMNS:
        table_drifts = [d for d in all_drifts if d["table_name"] == f"raw.{table_name}"]
        if table_drifts:
            await db.execute(
                text(
                    "INSERT INTO meta.schema_drifts "
                    "(source, table_name, severity, kind, column_name, old_type, new_type, "
                    "auto_adapted, action_required, downstream_impact) "
                    "VALUES (:source, :table_name, :severity, :kind, :column_name, :old_type, "
                    ":new_type, :auto_adapted, :action_required, :downstream_impact) "
                    "ON CONFLICT (table_name, column_name, kind) "
                    "DO UPDATE SET last_checked_at = now(), "
                    "old_type = EXCLUDED.old_type, new_type = EXCLUDED.new_type, "
                    "severity = EXCLUDED.severity, auto_adapted = EXCLUDED.auto_adapted, "
                    "action_required = EXCLUDED.action_required, "
                    "downstream_impact = EXCLUDED.downstream_impact"
                ),
                table_drifts,
            )

        # Composite (column_name, kind) keys, as a single delimited string
        # per key rather than SQL row-value tuples -- simpler and more
        # portable than binding a list of composite tuples through
        # asyncpg for a `NOT IN` clause.
        still_present_keys = [f"{d['column_name']}:::{d['kind']}" for d in table_drifts]
        await db.execute(
            text(
                "DELETE FROM meta.schema_drifts "
                "WHERE table_name = :table_name "
                "AND (column_name || ':::' || kind) <> ALL(:still_present_keys)"
            ),
            {
                "table_name": f"raw.{table_name}",
                "still_present_keys": still_present_keys,
            },
        )

    return all_drifts


async def get_recorded_drifts(db: AsyncSession) -> list[dict[str, Any]]:
    """Read back `meta.schema_drifts` as-is, without re-running detection
    — used by `GET /v1/data-quality/schema` between the 5-minute cache
    windows/detection runs."""
    result = await db.execute(
        text(
            "SELECT id, source, table_name, severity, kind, column_name, old_type, new_type, "
            "auto_adapted, action_required, downstream_impact, first_seen_at, last_checked_at "
            "FROM meta.schema_drifts ORDER BY first_seen_at DESC"
        )
    )
    return [dict(row) for row in result.mappings().all()]


async def count_recent_drifts(db: AsyncSession, since: Any) -> dict[str, int]:
    result = await db.execute(
        text(
            "SELECT auto_adapted, count(*) as cnt FROM meta.schema_drifts "
            "WHERE first_seen_at >= :since GROUP BY auto_adapted"
        ),
        {"since": since},
    )
    rows = {row["auto_adapted"]: row["cnt"] for row in result.mappings().all()}
    auto_adapted = int(rows.get(True, 0))
    needs_action = int(rows.get(False, 0))
    return {
        "total_drifts_24h": auto_adapted + needs_action,
        "auto_adapted": auto_adapted,
        "needs_action": needs_action,
    }
