"""`GET /v1/data-sources[/{id}]` and `PATCH /v1/data-sources/{id}` logic.

Ported from data-pipeline's identical module, now that the admin-gated
endpoints these back are in scope too (`app.core.security`'s
verification-only JWT bearer auth — see that module's own docstring).

Merges three things per `app.models.datasources.CATALOG` entry:

1. Static deployment config (name, category, default cron, URL, license,
   ...) — the catalog itself.
2. Admin-editable config/overrides (`enabled`, `cron`, `timezone`,
   `description`, `auth_type`, `metadata`, `version`, timestamps) —
   `meta.data_sources` (the same shared Postgres schema data-pipeline
   uses — this service's `DATABASE_URL` points at the same instance,
   per Phase 0's "no separate ingestion database" decision). NULL
   columns there mean "no override, use the catalog default".
3. Live health/run stats — `meta._ingest_log` (last 7 days) and the
   Redis-backed circuit breaker (`app.service.pipeline.circuit_breaker`).

The catalog only has 5 entries, so filtering/sorting/pagination happen in
Python over the fully-merged list rather than pushed into SQL — simplest
correct thing at this scale, and keeps the health-status/percentile math
in one testable place.

Two independent caches, per the endpoints' cache contracts:
`datasources:list:v1:{query_hash}` (30s, list) and
`datasources:one:v1:{id}` (30s, single). `PATCH` clears both.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import ApiError
from app.db.redis import get_breaker
from app.db.session import get_session
from app.models.datasources import CATALOG, CATALOG_BY_ID, DataSourceDef
from app.schemas.datasources import (
    AuthInfo,
    DataSourceOut,
    DataSourcesListResponse,
    DataSourcesMeta,
    HealthInfo,
    HealthStatus,
    LastRunInfo,
    PatchDataSourceRequest,
    ScheduleInfo,
)
from app.service.pipeline.circuit_breaker import CircuitState

LIST_CACHE_TTL_SECONDS = 30
ONE_CACHE_TTL_SECONDS = 30
LIST_CACHE_PREFIX = "datasources:list:v1"
ONE_CACHE_PREFIX = "datasources:one:v1"
CACHE_TTL_SECONDS = LIST_CACHE_TTL_SECONDS
CACHE_KEY_PREFIX = LIST_CACHE_PREFIX
_STATS_WINDOW = timedelta(days=7)

# Widened to allow `*` within the character class so `*/N` step syntax
# validates (every cron in our catalog uses it: `*/5`, `*/15`, `*/30`),
# while keeping the same "5 space-separated fields" shape check.
CRON_RE = re.compile(r"^[0-9,\-/*]+( [0-9,\-/*]+){4}$")


@dataclass
class ListDataSourcesQuery:
    category: str | None = None
    enabled: bool | None = None
    health: str | None = None
    search: str | None = None
    sort: str = "name"
    order: str = "asc"
    limit: int = 50
    cursor: str | None = None

    def cache_key(self) -> str:
        payload = {
            "category": self.category,
            "enabled": self.enabled,
            "health": self.health,
            "search": self.search,
            "sort": self.sort,
            "order": self.order,
            "limit": self.limit,
            "cursor": self.cursor,
        }
        digest = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()
        return f"{CACHE_KEY_PREFIX}:{digest}"


def _percentile(values: list[float], pct: float) -> int | None:
    """Linear-interpolation percentile (numpy's default `"linear"` method),
    written out longhand to avoid pulling numpy in just for this."""
    if not values:
        return None
    ordered = sorted(values)
    rank = (len(ordered) - 1) * (pct / 100)
    lo, hi = math.floor(rank), math.ceil(rank)
    if lo == hi:
        return round(ordered[int(rank)])
    lo_val = ordered[lo] * (hi - rank)
    hi_val = ordered[hi] * (rank - lo)
    return round(lo_val + hi_val)


def _derive_health_status(
    *,
    enabled: bool,
    circuit_state: CircuitState,
    consecutive_failures: int,
    success_rate_24h: float | None,
    failure_threshold: int,
) -> HealthStatus:
    if not enabled:
        return "paused"
    if circuit_state == CircuitState.OPEN or consecutive_failures >= failure_threshold:
        return "failing"
    if consecutive_failures > 0 or (
        success_rate_24h is not None and success_rate_24h < 100
    ):
        return "degraded"
    return "healthy"


_CONFIG_COLUMNS = (
    "id, enabled, cron, timezone, description, auth_type, metadata, "
    "version, created_at, updated_at"
)


def _normalise_config_row(row: dict[str, Any]) -> dict[str, Any]:
    """asyncpg/SQLAlchemy usually hand back `jsonb` already parsed into a
    dict, but a raw `text()` query doesn't guarantee it — normalise so
    callers can always treat `metadata` as a dict."""
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        row = {**row, "metadata": json.loads(metadata)}
    return row


async def _fetch_source_configs(
    db: AsyncSession, ids: list[str]
) -> dict[str, dict[str, Any]]:
    result = await db.execute(
        text(f"SELECT {_CONFIG_COLUMNS} FROM meta.data_sources WHERE id = ANY(:ids)"),  # nosec B608 -- `_CONFIG_COLUMNS` is a fixed module-level constant, not user input
        {"ids": ids},
    )
    return {
        row["id"]: _normalise_config_row(dict(row)) for row in result.mappings().all()
    }


async def _update_config(
    db: AsyncSession,
    id: str,
    *,
    enabled: bool,
    cron: str,
    timezone: str,
    description: str,
    auth_type: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    result = await db.execute(
        text(
            "UPDATE meta.data_sources SET "
            "enabled = :enabled, cron = :cron, timezone = :timezone, "
            "description = :description, auth_type = :auth_type, "
            "metadata = :metadata::jsonb, version = version + 1, updated_at = now() "
            f"WHERE id = :id RETURNING {_CONFIG_COLUMNS}"  # nosec B608 -- `_CONFIG_COLUMNS` is a fixed module-level constant, not user input
        ),
        {
            "id": id,
            "enabled": enabled,
            "cron": cron,
            "timezone": timezone,
            "description": description,
            "auth_type": auth_type,
            "metadata": json.dumps(metadata),
        },
    )
    row = result.mappings().first()
    if row is None:  # pragma: no cover - id is checked against the catalog first
        raise ApiError(404, "not_found", f"No data source with id '{id}'")
    return _normalise_config_row(dict(row))


async def fetch_run_rows(
    sources: list[str], since: datetime
) -> dict[str, list[dict[str, Any]]]:
    """`meta._ingest_log`/`meta.anomalies` -- uses its own dedicated
    `get_session()` (2026-08-12) rather than accepting a caller-supplied
    `db`, since this helper is called from many different contexts (some
    mixed with `meta.data_sources` config reads, some not) and is always
    a self-contained, independent read either way -- no caller has ever
    relied on it sharing their own transaction.

    **Real correction (2026-08-12, same day)**: `meta._ingest_log`/`meta.
    anomalies` were briefly moved to a separate `LOG_DB_URL` database
    alongside this service's other audit-log tables, then moved back --
    `meta.anomalies` is a real dbt *source* (`services/waerehouse/dbt/
    ecolens/models/staging/stg_anomalies.sql`, feeding `int_anomaly_by_
    demand.sql` -> `fct_energy_demand`'s `is_anomalous`/`anomaly_score`
    columns, which the dashboard's anomaly-detection overview chart reads
    directly). dbt's own connection profile has no knowledge of
    `LOG_DB_URL` at all, so moving this table made that real, live chart
    permanently stale the moment it happened -- confirmed live: it kept
    showing pre-move anomalies (including ones below the real 0.95
    score gate `pipeline.anomaly.detect_anomalies` enforces) forever,
    since new post-gate rows were landing in a database dbt never reads.
    `meta._ingest_log` came back with it, not because it has its own dbt
    dependency (it doesn't), but because `meta.anomalies.run_id` has a
    real foreign key into it -- the two can never live in different
    databases from each other. Every *other* audit-log table this
    service/`services/waerehouse`/`services/forecast-api` write
    (`_training_log`, `_dbt_build_log`, `_feature_selection_log`,
    `_marts_archive_log`, `_retention_log`) has no dbt-source dependency
    and correctly stays on `LOG_DB_URL`."""
    async with get_session() as db:
        result = await db.execute(
            text(
                "SELECT l.id, l.source, l.status, l.started_at, l.finished_at, "
                "l.rows_landed, l.rows_loaded, l.error_message, l.triggered_by, "
                "COALESCE(a.cnt, 0) AS anomalies_flagged "
                "FROM meta._ingest_log l "
                "LEFT JOIN (SELECT run_id, count(*) AS cnt FROM meta.anomalies GROUP BY run_id) a "
                "  ON a.run_id = l.id "
                "WHERE l.source = ANY(:sources) AND l.started_at >= :since "
                "ORDER BY l.source, l.started_at DESC"
            ),
            {"sources": sources, "since": since},
        )
        by_source: dict[str, list[dict[str, Any]]] = {s: [] for s in sources}
        for row in result.mappings().all():
            by_source[row["source"]].append(dict(row))
        return by_source


def _derive_cadence(cron: str) -> str:
    """Human-readable cadence for an admin-supplied cron the catalog has
    no hand-authored description for (`entry.cadence` is only accurate for
    `entry.cron` itself)."""
    parts = cron.split()
    if len(parts) != 5:
        return f"Custom schedule ({cron})"
    minute, hour, dom, month, dow = parts
    if minute.startswith("*/") and (hour, dom, month, dow) == ("*", "*", "*", "*"):
        return f"Every {minute[2:]} minutes"
    if hour.startswith("*/") and minute == "0" and (dom, month, dow) == ("*", "*", "*"):
        return f"Every {hour[2:]} hours"
    return f"Custom schedule ({cron})"


def _build_entry(
    entry: DataSourceDef,
    *,
    config: dict[str, Any],
    runs: list[dict[str, Any]],
    circuit_state: CircuitState,
    now: datetime,
    failure_threshold: int,
) -> DataSourceOut:
    enabled = bool(config.get("enabled", True))
    cron = config.get("cron") or entry.cron
    timezone = config.get("timezone") or entry.timezone
    description = config.get("description") or entry.description
    auth_type = config.get("auth_type") or entry.auth_type
    metadata = {**entry.metadata, **(config.get("metadata") or {})}
    cadence = entry.cadence if cron == entry.cron else _derive_cadence(cron)

    consecutive_failures = 0
    for run in runs:
        if run["status"] == "failed":
            consecutive_failures += 1
        else:
            break

    cutoff_24h = now - timedelta(hours=24)
    runs_24h = [r for r in runs if r["started_at"] >= cutoff_24h]

    def _success_rate(rows: list[dict[str, Any]]) -> float | None:
        if not rows:
            return None
        successes = sum(1 for r in rows if r["status"] == "success")
        return round(100 * successes / len(rows), 1)

    durations_ms = [
        (r["finished_at"] - r["started_at"]).total_seconds() * 1000
        for r in runs
        if r["finished_at"] is not None
    ]

    status = _derive_health_status(
        enabled=enabled,
        circuit_state=circuit_state,
        consecutive_failures=consecutive_failures,
        success_rate_24h=_success_rate(runs_24h),
        failure_threshold=failure_threshold,
    )

    last_run_row = runs[0] if runs else None
    last_run = None
    if last_run_row is not None:
        duration_ms = None
        if last_run_row["finished_at"] is not None:
            duration_ms = round(
                (
                    last_run_row["finished_at"] - last_run_row["started_at"]
                ).total_seconds()
                * 1000
            )
        rows_landed = last_run_row.get("rows_landed")
        rows_loaded = last_run_row.get("rows_loaded")
        last_run = LastRunInfo(
            id=str(last_run_row["id"]),
            status=last_run_row["status"],
            started_at=last_run_row["started_at"],
            finished_at=last_run_row["finished_at"],
            duration_ms=duration_ms,
            records_fetched=rows_landed,
            records_inserted=rows_loaded,
            duplicates_skipped=(
                max(0, rows_landed - rows_loaded)
                if rows_landed is not None and rows_loaded is not None
                else None
            ),
            anomalies_flagged=last_run_row.get("anomalies_flagged"),
            error=last_run_row["error_message"],
        )

    try:
        tz = ZoneInfo(timezone)
    except ZoneInfoNotFoundError:
        # Shouldn't happen — PATCH validates the timezone before persisting
        # it — but a GET must never 500 over bad stored data, so fail open
        # to UTC rather than raise.
        tz = ZoneInfo("UTC")
    next_run_at = croniter(cron, now.astimezone(tz)).get_next(datetime).astimezone(UTC)

    created_at = config.get("created_at") or now
    updated_at = config.get("updated_at") or now

    return DataSourceOut(
        id=entry.id,
        name=entry.name,
        category=entry.category,
        description=description,
        url=entry.url,
        license=entry.license,
        auth=AuthInfo(type=auth_type),
        schedule=ScheduleInfo(
            cron=cron,
            cadence=cadence,
            timezone=timezone,
            enabled=enabled,
            next_run_at=next_run_at,
            last_run_at=last_run_row["started_at"] if last_run_row else None,
        ),
        health=HealthInfo(
            status=status,
            success_rate_pct_24h=_success_rate(runs_24h),
            success_rate_pct_7d=_success_rate(runs),
            p50_duration_ms=_percentile(durations_ms, 50),
            p95_duration_ms=_percentile(durations_ms, 95),
            p99_duration_ms=_percentile(durations_ms, 99),
            consecutive_failures=consecutive_failures,
            circuit_breaker=circuit_state.value,
            last_check_at=now,
        ),
        last_run=last_run,
        regions=list(entry.regions),
        metadata=metadata,
        version=int(config.get("version", 1)),
        created_at=created_at,
        updated_at=updated_at,
    )


def _sort_key(item: DataSourceOut, sort: str) -> Any:
    if sort == "name":
        return item.name.lower()
    if sort == "category":
        return item.category
    if sort == "last_run_at":
        return item.schedule.last_run_at
    if sort == "success_rate_pct":
        return item.health.success_rate_pct_24h
    raise ValueError(f"unknown sort field: {sort}")


def _sort_and_paginate(
    items: list[DataSourceOut], query: ListDataSourcesQuery
) -> tuple[list[DataSourceOut], str | None, bool]:
    # None always sorts last, regardless of direction.
    non_null = sorted(
        (i for i in items if _sort_key(i, query.sort) is not None),
        key=lambda item: _sort_key(item, query.sort),
        reverse=(query.order == "desc"),
    )
    null = [i for i in items if _sort_key(i, query.sort) is None]
    items = non_null + null

    offset = 0
    if query.cursor:
        try:
            offset = int(base64.urlsafe_b64decode(query.cursor.encode()).decode())
        except Exception:
            offset = 0

    page = items[offset : offset + query.limit]
    has_more = offset + query.limit < len(items)
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + query.limit).encode()).decode()
        if has_more
        else None
    )
    return page, next_cursor, has_more


async def list_data_sources(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    query: ListDataSourcesQuery,
) -> DataSourcesListResponse:
    cache_key = query.cache_key()
    cached = await redis.get(cache_key)
    if cached is not None:
        return DataSourcesListResponse.model_validate_json(cached)

    now = datetime.now(UTC)
    ids = [entry.id for entry in CATALOG]
    sources = [entry.ingest_source for entry in CATALOG]

    # Sequential, not gathered: both queries run on the same AsyncSession,
    # and SQLAlchemy's AsyncSession isn't safe for concurrent operations.
    # The circuit-breaker reads use a separate Redis client, so those can
    # still run concurrently with each other.
    configs = await _fetch_source_configs(db, ids)
    run_rows = await fetch_run_rows(sources, now - _STATS_WINDOW)
    breaker_states = await asyncio.gather(*(get_breaker(src).state for src in sources))
    circuit_by_source = dict(zip(sources, breaker_states, strict=True))

    built = [
        _build_entry(
            entry,
            config=configs.get(entry.id, {}),
            runs=run_rows.get(entry.ingest_source, []),
            circuit_state=circuit_by_source[entry.ingest_source],
            now=now,
            failure_threshold=settings.circuit_breaker_failure_threshold,
        )
        for entry in CATALOG
    ]

    filtered = built
    if query.category is not None:
        filtered = [i for i in filtered if i.category == query.category]
    if query.enabled is not None:
        filtered = [i for i in filtered if i.schedule.enabled == query.enabled]
    if query.health is not None:
        filtered = [i for i in filtered if i.health.status == query.health]
    if query.search:
        needle = query.search.lower()
        filtered = [
            i
            for i in filtered
            if needle in i.name.lower() or needle in i.description.lower()
        ]

    meta = DataSourcesMeta(
        total=len(filtered),
        enabled_count=sum(1 for i in filtered if i.schedule.enabled),
        disabled_count=sum(1 for i in filtered if not i.schedule.enabled),
        healthy_count=sum(1 for i in filtered if i.health.status == "healthy"),
        degraded_count=sum(1 for i in filtered if i.health.status == "degraded"),
        failing_count=sum(1 for i in filtered if i.health.status == "failing"),
        paused_count=sum(1 for i in filtered if i.health.status == "paused"),
        as_of=now,
        next_refresh_at=now + timedelta(seconds=CACHE_TTL_SECONDS),
    )

    page, next_cursor, has_more = _sort_and_paginate(filtered, query)

    response = DataSourcesListResponse(
        meta=meta, data=page, next_cursor=next_cursor, has_more=has_more
    )

    await redis.set(cache_key, response.model_dump_json(), ex=CACHE_TTL_SECONDS)
    return response


def require_catalog_entry(id: str) -> DataSourceDef:
    entry = CATALOG_BY_ID.get(id)
    if entry is None:
        raise ApiError(404, "not_found", f"No data source with id '{id}'")
    return entry


async def _build_one(
    entry: DataSourceDef,
    db: AsyncSession,
    settings: Settings,
    config: dict[str, Any],
) -> DataSourceOut:
    now = datetime.now(UTC)
    run_rows = await fetch_run_rows([entry.ingest_source], now - _STATS_WINDOW)
    circuit_state = await get_breaker(entry.ingest_source).state
    return _build_entry(
        entry,
        config=config,
        runs=run_rows.get(entry.ingest_source, []),
        circuit_state=circuit_state,
        now=now,
        failure_threshold=settings.circuit_breaker_failure_threshold,
    )


async def get_data_source(
    db: AsyncSession, redis: Redis, settings: Settings, id: str
) -> DataSourceOut:
    entry = require_catalog_entry(id)

    cache_key = f"{ONE_CACHE_PREFIX}:{id}"
    cached = await redis.get(cache_key)
    if cached is not None:
        return DataSourceOut.model_validate_json(cached)

    configs = await _fetch_source_configs(db, [id])
    result = await _build_one(entry, db, settings, configs.get(id, {}))

    await redis.set(cache_key, result.model_dump_json(), ex=ONE_CACHE_TTL_SECONDS)
    return result


def _validate_cron(cron: str) -> None:
    if not CRON_RE.match(cron):
        raise ApiError(
            400, "invalid_cron", f"'{cron}' is not a valid 5-field cron expression"
        )
    try:
        croniter(cron)
    except (ValueError, KeyError) as exc:
        raise ApiError(
            400, "invalid_cron", f"'{cron}' is not a valid cron expression"
        ) from exc


def _validate_timezone(name: str) -> None:
    try:
        ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ApiError(
            400, "invalid_timezone", f"'{name}' is not a valid IANA timezone"
        ) from exc


async def _invalidate_list_cache(redis: Redis) -> None:
    async for key in redis.scan_iter(match=f"{LIST_CACHE_PREFIX}:*"):
        await redis.delete(key)


async def update_data_source(
    db: AsyncSession,
    redis: Redis,
    settings: Settings,
    id: str,
    body: PatchDataSourceRequest,
    if_match: str | None,
    edited_by: str,
) -> DataSourceOut:
    entry = require_catalog_entry(id)

    configs = await _fetch_source_configs(db, [id])
    current = configs.get(id, {})
    current_version = int(current.get("version", 1))

    if if_match is not None and if_match != str(current_version):
        raise ApiError(
            409,
            "version_mismatch",
            f"If-Match '{if_match}' does not match current version {current_version}",
        )

    new_cron = current.get("cron") or entry.cron
    new_timezone = current.get("timezone") or entry.timezone
    new_enabled = bool(current.get("enabled", True))
    new_description = current.get("description") or entry.description
    new_auth_type = current.get("auth_type") or entry.auth_type
    merged_metadata = dict(current.get("metadata") or {})

    if body.schedule is not None:
        if body.schedule.cron is not None:
            _validate_cron(body.schedule.cron)
            new_cron = body.schedule.cron
        if body.schedule.timezone is not None:
            _validate_timezone(body.schedule.timezone)
            new_timezone = body.schedule.timezone
        if body.schedule.enabled is not None:
            new_enabled = body.schedule.enabled
    if body.description is not None:
        new_description = body.description
    if body.auth is not None:
        new_auth_type = body.auth.type
    if body.metadata:
        merged_metadata.update(body.metadata)
    merged_metadata["last_edited_by"] = edited_by

    updated_row = await _update_config(
        db,
        id,
        enabled=new_enabled,
        cron=new_cron,
        timezone=new_timezone,
        description=new_description,
        auth_type=new_auth_type,
        metadata=merged_metadata,
    )

    result = await _build_one(entry, db, settings, updated_row)

    # Clear both caches on success: the single-item key for this id, and
    # every cached list page (a changed source might now match/not-match
    # an arbitrary filter combo baked into some `query_hash`, so a partial
    # invalidation can't target just the affected list entries).
    await redis.delete(f"{ONE_CACHE_PREFIX}:{id}")
    await _invalidate_list_cache(redis)

    return result
