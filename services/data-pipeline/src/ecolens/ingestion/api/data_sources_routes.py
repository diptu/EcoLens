"""`GET /v1/data-sources`, `GET /v1/data-sources/{id}`, `PATCH
/v1/data-sources/{id}`, `POST /v1/data-sources/{id}/run`, `POST
/v1/data-sources/{id}/backfill`, `GET /v1/data-sources/{id}/health`,
`GET /v1/data-sources/{id}/history` -- root TODO.md's "Data Sources
admin page" spec: list/get every configured ingestion source with its
schedule, health, and last-run outcome; let an admin edit its
schedule/enabled state/description/auth type/metadata; trigger an
immediate fetch or a historical backfill; and inspect higher-resolution
health/run history for one source.

**`/run` and `/backfill` reuse `ingestion/api/routes.py`'s existing
`_ingest_*_historical()` functions** (the same fetch-validate-upsert
building blocks `POST /ingestion/historical` already uses) rather than
duplicating per-source fetch orchestration -- `/run` calls them for
just today's date (a live "fetch now" is, mechanically, a one-day
backfill); `/backfill` for the requested range, chunked. Two real
consequences of reusing day-granularity functions: (1) `/backfill`'s
`chunk` parameter only has day-level effective resolution regardless
of a finer-grained ISO 8601 duration like `PT1H` (this repo's
underlying ingest primitives operate on whole calendar days, not
sub-day windows); (2) neither endpoint runs "in Prefect" -- no Prefect
integration exists anywhere in this repo, both dispatch a
`BackgroundTasks` job and poll via `GET .../history`, the same pattern
`POST /ingestion/historical`'s own `JobTracker` already established.

`deduplicate` is accepted, stored, and echoed back on both endpoints,
but doesn't change real behavior -- `write_historical`'s upsert-by-
unique-key already makes every write idempotent regardless of this
flag (there's no separate sha256-content-match dedup layer to toggle).

`force` (bypass the circuit breaker) is real, for whatever it's
worth: nothing in this repo's live fetchers actually calls
`CircuitBreaker.record_failure()` today (`ecolens.ingestion.core.
circuit_breaker.CircuitBreaker` is built and wired into this router's
own health reporting, but not yet plumbed into the fetchers
themselves -- see `service/aemo_wem/engine.py`'s own `# See ECO-101`
comment) -- so in practice the breaker is always closed and `force`
never has anything to bypass *today*. Checking it here is still the
right, forward-compatible behavior once that wiring lands, not a
no-op left in by mistake.

`errors_by_code_24h` (on `/health`) is a best-effort heuristic
classification of each failed run's free-text `error` string into the
spec's 4 named codes (substring matching, not a first-class tracked
field) -- an error that doesn't match any known pattern isn't counted
into any bucket, rather than guessed into the wrong one.

Real sources, not the spec's own literal "9" -- only 5 exist in this
repo (`IngestionSettings.table_for_source()`'s 5 keys, canonically
listed in `core/data_source_overrides.py`, with static descriptive
metadata in `core/data_source_catalog.py`); reporting a fabricated 9
would misrepresent this API's own state to whatever dashboard renders
it, the same reasoning `warehouse/service/executive_kpis.py` already
documents for its 3 honestly-unavailable KPI cards.

**What's real vs. persisted-but-not-yet-authoritative vs. honestly
unavailable, by field:**
  - `schedule.enabled` -- real. Enforced in all 5
    `scripts/trigger_ingest_*.py` (`is_source_enabled()`).
  - `schedule.cron`/`timezone`/`next_run_at` -- persisted, validated,
    and *projected* (`next_run_at` computed via `croniter` from the
    stored cron+timezone), but nothing in the actual ingestion pipeline
    reads them authoritatively yet -- see
    `core/data_source_overrides.py`'s own docstring for why.
  - `health.circuit_breaker`/`consecutive_failures` -- real (the same
    Redis-backed `CircuitBreaker` every live fetcher reports to).
  - `health.success_rate_pct_24h/7d`, `p50/p95/p99_duration_ms`,
    `last_run` -- real, computed from `core/run_history.py`'s recorded
    run outcomes (added alongside this endpoint specifically so these
    fields could be real instead of fabricated).
  - `last_run.duplicates_skipped` -- honestly `null`. `write_historical`'s
    upsert can't currently distinguish a new row from an overwritten
    one; see `run_history.py`'s own docstring.
  - `auth`/`url`/`license`/`category`/`description`/`regions` --
    static, factual metadata (`core/data_source_catalog.py`), overridable
    per-source via `PATCH` (`description`, `auth.type`, `metadata`).

**Auth:** the spec calls for JWT (admin/analyst for GET, admin-only for
PATCH). No JWT verification library, iam-service, or user/role model
exists anywhere in this repo. This router keeps the same posture every
other route on `ecolens.api.app` already has (no auth beyond
`Settings.api_cors_origins`) rather than fabricating JWT/RBAC
infrastructure that doesn't exist.
"""

from __future__ import annotations

import asyncio
import base64
import re
import uuid
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from croniter import croniter  # type: ignore[import-untyped]
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query
from pydantic import BaseModel

import ecolens.ingestion.api.routes as ingestion_routes
from ecolens.ingestion.core.circuit_breaker import CircuitBreaker
from ecolens.ingestion.core.data_source_catalog import CATALOG
from ecolens.ingestion.core.data_source_overrides import (
    DEFAULT_CRON_EXPRESSION,
    DEFAULT_TIMEZONE,
    SOURCE_IDS,
    get_override,
    set_override,
    validate_cron_expression,
    validate_timezone,
)
from ecolens.ingestion.core.data_sources_cache import (
    get_cached,
    invalidate_list_cache,
    invalidate_one_cache,
    list_cache_key,
    one_cache_key,
    set_cached,
)
from ecolens.ingestion.core.run_history import (
    RunRecord,
    compute_stats,
    read_runs,
    record_run,
)
from ecolens.ingestion.core.run_locks import (
    acquire_backfill_lock,
    acquire_run_lock,
    get_idempotent_response,
    release_backfill_lock,
    release_run_lock,
    store_idempotent_response,
)
from ecolens.ingestion.core.settings import IngestionSettings, get_ingestion_settings
from ecolens.ingestion.db import duckdb_store
from ecolens.shared.cache.redis_client import get_redis_client
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/v1/data-sources", tags=["data-sources"])

_ID_PREFIX = "ds-"


def _public_id(source_id: str) -> str:
    return f"{_ID_PREFIX}{source_id.replace('_', '-')}"


def _internal_id(public_id: str) -> str | None:
    if not public_id.startswith(_ID_PREFIX):
        return None
    candidate = public_id[len(_ID_PREFIX) :].replace("-", "_")
    return candidate if candidate in SOURCE_IDS else None


def _error(status_code: int, code: str, message: str) -> HTTPException:
    """Error body is `{"detail": {"code": ..., "message": ...}}` --
    matches this app's existing `{"detail": ...}` convention (every
    other route on `ecolens.api.app` already uses plain `HTTPException
    (detail=...)`) while still delivering the endpoint spec's own
    machine-readable error `code`s (`invalid_cron`, `invalid_timezone`,
    `not_found`, `version_mismatch`) -- forking a second top-level
    envelope shape for one route would be a worse inconsistency than
    nesting the code one level down from the spec's literal
    `{"error": {"code": ...}}`.
    """
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


# ── schedule helpers ──────────────────────────────────────────────────


def _cadence_text(cron_expr: str) -> str:
    """Best-effort human description -- only the `*/N * * * *` shape
    (what every source in this repo actually uses) gets a friendly
    string; anything more exotic (admin-set ranges/lists) falls back to
    echoing the raw cron rather than a wrong or overclaimed description.
    """
    minute_field = cron_expr.split()[0]
    if minute_field == "*":
        return "Every minute"
    if minute_field.startswith("*/"):
        n = minute_field[2:]
        return "Every minute" if n == "1" else f"Every {n} minutes"
    return cron_expr


def _next_run_at(cron_expr: str, tz_name: str, now: datetime) -> str | None:
    try:
        tz = ZoneInfo(tz_name)
        local_now = now.astimezone(tz)
        next_dt = croniter(cron_expr, local_now).get_next(datetime)
        return next_dt.astimezone(timezone.utc).isoformat()
    except Exception as exc:  # noqa: BLE001 - a bad stored cron must degrade this one field, not the whole response
        log.warning(
            "data_sources.next_run_at_failed",
            cron=cron_expr,
            tz=tz_name,
            error=str(exc),
        )
        return None


# ── health helpers ────────────────────────────────────────────────────


def _freshness_threshold_minutes(source: str, settings: IngestionSettings) -> float:
    if source == "bom":
        return settings.data_source_health_threshold_minutes_bom
    if source == "aemo_holidays":
        return settings.data_source_health_threshold_minutes_holidays
    return settings.data_source_health_threshold_minutes_aemo


async def _circuit_breaker_state(source: str) -> dict[str, Any]:
    """`{"state": "unavailable", ...}` (not `"closed"`) when Redis can't
    be reached -- "we don't know" must never be reported as "definitely
    fine" on a health endpoint.
    """
    try:
        redis = get_redis_client()
        breaker = CircuitBreaker(source, redis)
        return await breaker.get_state()
    except Exception as exc:  # noqa: BLE001 - a health-*reporting* endpoint must degrade, never 500
        log.warning(
            "data_sources.circuit_breaker_unavailable", source=source, error=str(exc)
        )
        return {
            "state": "unavailable",
            "failures": None,
            "retry_after_seconds": None,
            "opened_at": None,
            "half_open_at": None,
            "recovery_seconds": None,
        }


def _health_status(
    *,
    enabled: bool,
    freshness_status: str,
    circuit_state: str,
    consecutive_failures: int,
) -> str:
    """Maps this endpoint's real underlying signals (freshness,
    circuit-breaker state, live failure count) onto the spec's own
    4-value enum (`healthy`/`degraded`/`failing`/`paused`) -- a
    combination of already-real facts, not a 5th independently-tracked
    number.
    """
    if not enabled:
        return "paused"
    if circuit_state == "open" or freshness_status == "missing":
        return "failing"
    if (
        circuit_state in ("half_open", "unavailable")
        or freshness_status == "stale"
        or consecutive_failures > 0
    ):
        return "degraded"
    return "healthy"


async def _build_health(
    source_id: str, settings: IngestionSettings, *, enabled: bool, now: datetime
) -> dict[str, Any]:
    threshold_minutes = _freshness_threshold_minutes(source_id, settings)
    latest_ts = duckdb_store.latest_fetched_at(source_id)
    freshness_status = "missing"
    if latest_ts is not None:
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        age_minutes = (now - latest_ts).total_seconds() / 60
        freshness_status = "fresh" if age_minutes <= threshold_minutes else "stale"

    circuit = await _circuit_breaker_state(source_id)
    consecutive_failures = circuit.get("failures") or 0

    stats_24h = compute_stats(source_id, since=now - _DAY)
    stats_7d = compute_stats(source_id, since=now - _WEEK)

    return {
        "status": _health_status(
            enabled=enabled,
            freshness_status=freshness_status,
            circuit_state=circuit["state"],
            consecutive_failures=consecutive_failures,
        ),
        "success_rate_pct_24h": stats_24h.success_rate_pct,
        "success_rate_pct_7d": stats_7d.success_rate_pct,
        "p50_duration_ms": stats_7d.p50_duration_ms,
        "p95_duration_ms": stats_7d.p95_duration_ms,
        "p99_duration_ms": stats_7d.p99_duration_ms,
        "consecutive_failures": consecutive_failures,
        "circuit_breaker": circuit["state"],
        "last_check_at": now.isoformat(),
    }


def _build_last_run(record: RunRecord | None) -> dict[str, Any] | None:
    if record is None:
        return None
    return {
        "id": record.run_id,
        "status": record.status,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_ms": record.duration_ms,
        "records_fetched": record.records_fetched,
        "records_inserted": record.records_inserted,
        # Honestly unavailable, not fabricated -- see this module's own
        # docstring and run_history.py's for why.
        "duplicates_skipped": None,
        "anomalies_flagged": record.anomalies_flagged,
        "error": record.error,
    }


_DAY = timedelta(days=1)
_WEEK = timedelta(days=7)


async def _build_source_entry(
    source_id: str, settings: IngestionSettings
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    override = get_override(source_id, settings=settings)
    info = CATALOG[source_id]
    cron = override.cron or DEFAULT_CRON_EXPRESSION
    tz_name = override.timezone or DEFAULT_TIMEZONE

    runs = read_runs(source_id)
    latest_run = runs[-1] if runs else None

    health = await _build_health(source_id, settings, enabled=override.enabled, now=now)

    return {
        "id": _public_id(source_id),
        "name": info.name,
        "category": info.category,
        "description": override.description or info.description,
        "url": info.url,
        "license": info.license,
        "auth": {"type": override.auth_type or info.auth_type},
        "schedule": {
            "cron": cron,
            "cadence": _cadence_text(cron),
            "timezone": tz_name,
            "enabled": override.enabled,
            "next_run_at": _next_run_at(cron, tz_name, now),
            "last_run_at": latest_run.finished_at if latest_run else None,
        },
        "health": health,
        "last_run": _build_last_run(latest_run),
        "regions": list(info.regions),
        "metadata": override.metadata,
        "version": override.version,
        "created_at": runs[0].started_at if runs else None,
        "updated_at": override.updated_at,
    }


# ── request/response models ──────────────────────────────────────────


class ScheduleUpdate(BaseModel):
    cron: str | None = None
    timezone: str | None = None
    enabled: bool | None = None


class AuthUpdate(BaseModel):
    type: str | None = None


class DataSourcePatchRequest(BaseModel):
    schedule: ScheduleUpdate | None = None
    description: str | None = None
    auth: AuthUpdate | None = None
    metadata: dict[str, Any] | None = None


CategoryFilter = Literal["grid", "weather", "carbon", "fuel", "custom"]
HealthFilter = Literal["healthy", "degraded", "failing", "paused"]
SortField = Literal["name", "category", "last_run_at", "success_rate_pct_24h"]
SortOrder = Literal["asc", "desc"]


# ── routes ────────────────────────────────────────────────────────────


@router.get("")
async def list_data_sources(
    category: CategoryFilter | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    health: HealthFilter | None = Query(default=None),
    search: str | None = Query(default=None, max_length=64),
    sort: SortField = Query(default="name"),
    order: SortOrder = Query(default="asc"),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    """Every configured ingestion source, filtered/sorted/paginated.
    Always 200 -- a source with no data yet or an unreachable
    circuit-breaker Redis reports degraded `health` fields, not an
    error response for the whole list.

    `meta.total`/`next_cursor`/`has_more` reflect the *filtered* result
    set (standard pagination semantics); `meta.*_count` fields reflect
    the *whole* catalog regardless of the current filter (dashboard
    summary counts, e.g. for rendering filter-tab badges) -- the spec's
    own example doesn't disambiguate this, this is the more useful
    reading for a client rendering both a count badge and a filtered
    table from one response.
    """
    settings = get_ingestion_settings()
    query = {
        "category": category,
        "enabled": enabled,
        "health": health,
        "search": search,
        "sort": sort,
        "order": order,
        "limit": limit,
        "cursor": cursor,
    }
    cache_key = list_cache_key(query)
    cached = await get_cached(cache_key)
    if cached is not None:
        return cached

    all_entries = [await _build_source_entry(sid, settings) for sid in SOURCE_IDS]

    enabled_count = sum(1 for e in all_entries if e["schedule"]["enabled"])
    health_counts = {"healthy": 0, "degraded": 0, "failing": 0, "paused": 0}
    for e in all_entries:
        health_counts[e["health"]["status"]] += 1

    filtered = all_entries
    if category is not None:
        filtered = [e for e in filtered if e["category"] == category]
    if enabled is not None:
        filtered = [e for e in filtered if e["schedule"]["enabled"] == enabled]
    if health is not None:
        filtered = [e for e in filtered if e["health"]["status"] == health]
    if search:
        needle = search.lower()
        filtered = [
            e
            for e in filtered
            if needle in e["name"].lower() or needle in (e["description"] or "").lower()
        ]

    def _sort_key(entry: dict[str, Any]) -> Any:
        if sort == "name":
            return entry["name"]
        if sort == "category":
            return entry["category"]
        if sort == "last_run_at":
            return entry["schedule"]["last_run_at"] or ""
        return entry["health"]["success_rate_pct_24h"] or 0.0

    filtered.sort(key=_sort_key, reverse=(order == "desc"))

    offset = 0
    if cursor is not None:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except (ValueError, UnicodeDecodeError):
            raise _error(
                400, "invalid_cursor", f"malformed cursor: {cursor!r}"
            ) from None

    page = filtered[offset : offset + limit]
    has_more = offset + limit < len(filtered)
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        if has_more
        else None
    )

    now = datetime.now(timezone.utc)
    payload = {
        "meta": {
            "total": len(filtered),
            "enabled_count": enabled_count,
            "disabled_count": len(all_entries) - enabled_count,
            "healthy_count": health_counts["healthy"],
            "degraded_count": health_counts["degraded"],
            "failing_count": health_counts["failing"],
            "paused_count": health_counts["paused"],
            "as_of": now.isoformat(),
            "next_refresh_at": (now + timedelta(seconds=30)).isoformat(),
        },
        "data": page,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }
    await set_cached(cache_key, payload)
    return payload


@router.get("/{source_id}")
async def get_data_source(source_id: str) -> dict[str, Any]:
    internal_id = _internal_id(source_id)
    if internal_id is None:
        raise _error(404, "not_found", f"no data source with id {source_id!r}")

    cache_key = one_cache_key(internal_id)
    cached = await get_cached(cache_key)
    if cached is not None:
        return cached

    entry = await _build_source_entry(internal_id, get_ingestion_settings())
    await set_cached(cache_key, entry)
    return entry


@router.patch("/{source_id}")
async def patch_data_source(
    source_id: str,
    body: DataSourcePatchRequest,
    if_match: str | None = Header(default=None, alias="If-Match"),
) -> dict[str, Any]:
    """Edits schedule (cron/timezone/enabled), description, auth type,
    and/or metadata (merged, not replaced) for one source -- at least
    one field must be set. `If-Match` (recommended, not required),
    when given, must match the source's *current* `version` or the
    request 409s without applying anything.
    """
    internal_id = _internal_id(source_id)
    if internal_id is None:
        raise _error(404, "not_found", f"no data source with id {source_id!r}")

    schedule = body.schedule
    has_update = any(
        [
            schedule is not None
            and (schedule.cron, schedule.timezone, schedule.enabled)
            != (None, None, None),
            body.description is not None,
            body.auth is not None and body.auth.type is not None,
            body.metadata is not None,
        ]
    )
    if not has_update:
        raise _error(400, "empty_patch", "patch body must set at least one field")

    if (
        schedule is not None
        and schedule.cron is not None
        and not validate_cron_expression(schedule.cron)
    ):
        raise _error(
            400,
            "invalid_cron",
            f"invalid cron expression {schedule.cron!r}: expected 5 space-separated fields",
        )
    if (
        schedule is not None
        and schedule.timezone is not None
        and not validate_timezone(schedule.timezone)
    ):
        raise _error(
            400, "invalid_timezone", f"not a valid IANA timezone: {schedule.timezone!r}"
        )
    if body.description is not None and len(body.description) > 500:
        raise _error(
            400, "description_too_long", "description must be <=500 characters"
        )

    current = get_override(internal_id)
    if if_match is not None:
        try:
            if_match_version = int(if_match)
        except ValueError:
            raise _error(
                409, "version_mismatch", f"If-Match {if_match!r} is not a valid version"
            ) from None
        if if_match_version != current.version:
            raise _error(
                409,
                "version_mismatch",
                f"If-Match {if_match!r} does not match current version {current.version}",
            )

    set_override(
        internal_id,
        enabled=schedule.enabled if schedule else None,
        cron=schedule.cron if schedule else None,
        timezone_name=schedule.timezone if schedule else None,
        description=body.description,
        auth_type=body.auth.type if body.auth else None,
        metadata=body.metadata,
    )
    log.info("data_sources.patched", source=internal_id)

    await invalidate_list_cache()
    await invalidate_one_cache(internal_id)

    return await _build_source_entry(internal_id, get_ingestion_settings())


# ── /run + /backfill: shared execution + history recording ─────────────


async def _run_ingest_for_range(source_id: str, start: _date, end: _date) -> int:
    """Dispatches to `ingestion/api/routes.py`'s existing per-source
    backfill functions -- see this module's own docstring for why
    reusing these (day-granularity) primitives, rather than duplicating
    fetch orchestration, is the right call for both `/run` and
    `/backfill`.
    """
    if source_id == "bom":
        return await ingestion_routes._ingest_bom_historical(start, end)
    if source_id in ("aemo_nem", "aemo_wem"):
        return await ingestion_routes._ingest_aemo_historical(source_id, start, end)
    if source_id == "openelectricity":
        return await ingestion_routes._ingest_openelectricity_historical(start, end)
    if source_id == "aemo_holidays":
        return await ingestion_routes._ingest_holidays_historical(start, end)
    raise ValueError(
        f"no ingest dispatcher for {source_id!r}"
    )  # pragma: no cover - unreachable given SOURCE_IDS validation upstream


async def _execute_and_record(
    source_id: str, start: _date, end: _date, *, trigger: str, run_id: str
) -> None:
    """Runs one ingest call and always records the outcome to
    `run_history` -- `records_fetched`/`records_inserted` are both set
    to the same `written` count (the only number `_run_ingest_for_range`'s
    underlying functions return; they don't distinguish fetched-but-
    dropped-by-validation from written) -- an honest simplification
    documented here, not a silent inaccuracy.
    """
    started_at = datetime.now(timezone.utc)
    try:
        written = await _run_ingest_for_range(source_id, start, end)
    except Exception as exc:  # noqa: BLE001 - must still record the failed run before propagating
        record_run(
            source_id,
            status="failed",
            started_at=started_at,
            finished_at=datetime.now(timezone.utc),
            error=str(exc),
            run_id=run_id,
            trigger=trigger,
        )
        log.error(
            "data_sources.run_failed", source=source_id, run_id=run_id, error=str(exc)
        )
        return
    record_run(
        source_id,
        status="success" if written else "empty",
        started_at=started_at,
        finished_at=datetime.now(timezone.utc),
        records_fetched=written,
        records_inserted=written,
        run_id=run_id,
        trigger=trigger,
    )


# ── /run ─────────────────────────────────────────────────────────────


class RunRequest(BaseModel):
    force: bool = False
    deduplicate: bool = True


@router.post("/{source_id}/run", status_code=202)
async def trigger_data_source_run(
    source_id: str,
    background_tasks: BackgroundTasks,
    body: RunRequest = RunRequest(),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    x_reason: str | None = Header(default=None, alias="X-Reason"),
) -> dict[str, Any]:
    """Triggers an immediate fetch for one source (today's date, via
    the same day-granularity backfill primitives `/backfill` uses --
    see this module's own docstring). Returns 202 immediately; poll
    `GET .../history` for the outcome.
    """
    internal_id = _internal_id(source_id)
    if internal_id is None:
        raise _error(404, "not_found", f"no data source with id {source_id!r}")

    if idempotency_key:
        cached = await get_idempotent_response(idempotency_key)
        if cached is not None:
            return cached

    if not body.force:
        circuit = await _circuit_breaker_state(internal_id)
        if circuit["state"] == "open":
            raise _error(
                503,
                "circuit_open",
                f"circuit breaker open for {source_id!r}; pass force=true to bypass",
            )

    if not await acquire_run_lock(internal_id):
        raise _error(
            409, "already_running", f"a run for {source_id!r} is already in progress"
        )

    now = datetime.now(timezone.utc)
    run_id = f"run-{int(now.timestamp())}-{uuid.uuid4().hex[:5]}"
    today = now.date()

    async def _job() -> None:
        try:
            await _execute_and_record(
                internal_id, today, today, trigger="manual", run_id=run_id
            )
        finally:
            await release_run_lock(internal_id)

    background_tasks.add_task(_job)

    response = {
        "run_id": run_id,
        "source_id": _public_id(internal_id),
        "status": "queued",
        "queued_at": now.isoformat(),
        # A fixed, undocumented-as-measured estimate -- this is a
        # BackgroundTasks dispatch, not a real queue with observable
        # dequeue latency to report.
        "estimated_start_at": (now + timedelta(seconds=1)).isoformat(),
        "priority": "high",
        # No JWT/user-identity system exists (see module docstring) --
        # `null`, not a fabricated user, same reasoning as every other
        # auth-shaped gap in this router.
        "triggered_by": None,
        "reason": x_reason,
        "deduplicate": body.deduplicate,
        "force": body.force,
    }
    if idempotency_key:
        await store_idempotent_response(idempotency_key, response)
    log.info("data_sources.run_triggered", source=internal_id, run_id=run_id)
    return response


# ── /backfill ────────────────────────────────────────────────────────


_ISO8601_DURATION_RE = re.compile(
    r"^P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?$"
)


def _parse_iso8601_duration(value: str) -> timedelta:
    """A deliberately small subset of ISO 8601 durations (weeks/days/
    hours/minutes) -- covers every example the endpoint spec itself
    gives (`PT1H`, `P1D`, `P1W`), not a full ISO 8601 duration grammar
    (years/months, which aren't a fixed `timedelta` anyway).
    """
    match = _ISO8601_DURATION_RE.match(value)
    if not match or not any(match.groups()):
        raise ValueError(f"unsupported duration: {value!r}")
    parts = {k: int(v) for k, v in match.groupdict().items() if v is not None}
    return timedelta(
        weeks=parts.get("weeks", 0),
        days=parts.get("days", 0),
        hours=parts.get("hours", 0),
        minutes=parts.get("minutes", 0),
    )


def _split_into_chunks(
    start: datetime, end: datetime, step: timedelta
) -> list[tuple[datetime, datetime]]:
    chunks: list[tuple[datetime, datetime]] = []
    cur = start
    while cur < end:
        nxt = min(cur + step, end)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


_MAX_BACKFILL_RANGE = timedelta(days=90)


class BackfillRequest(BaseModel):
    start: datetime
    end: datetime
    chunk: str = "P1D"
    concurrency: int = 1
    deduplicate: bool = True


@router.post("/{source_id}/backfill", status_code=202)
async def trigger_data_source_backfill(
    source_id: str,
    background_tasks: BackgroundTasks,
    body: BackfillRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    internal_id = _internal_id(source_id)
    if internal_id is None:
        raise _error(404, "not_found", f"no data source with id {source_id!r}")

    if idempotency_key:
        cached = await get_idempotent_response(idempotency_key)
        if cached is not None:
            return cached

    now = datetime.now(timezone.utc)
    if body.start >= body.end:
        raise _error(400, "invalid_range", "'start' must be before 'end'")
    if body.end > now:
        raise _error(400, "invalid_range", "'end' must not be after now")
    if (body.end - body.start) > _MAX_BACKFILL_RANGE:
        raise _error(400, "range_too_large", "backfill range cannot exceed 90 days")
    if not 1 <= body.concurrency <= 4:
        raise _error(400, "invalid_range", "'concurrency' must be between 1 and 4")

    try:
        chunk_step = _parse_iso8601_duration(body.chunk)
    except ValueError:
        raise _error(
            400, "invalid_range", f"invalid 'chunk' duration: {body.chunk!r}"
        ) from None

    if not await acquire_backfill_lock(internal_id):
        raise _error(
            409,
            "backfill_in_progress",
            f"a backfill for {source_id!r} is already in progress",
        )

    chunks = _split_into_chunks(body.start, body.end, chunk_step)
    total_chunks = len(chunks)
    backfill_id = f"bf-{int(now.timestamp())}-{uuid.uuid4().hex[:5]}"

    async def _job() -> None:
        try:
            semaphore = asyncio.Semaphore(body.concurrency)

            async def _one_chunk(chunk_start: datetime, chunk_end: datetime) -> None:
                async with semaphore:
                    run_id = f"{backfill_id}-{chunk_start.date().isoformat()}"
                    await _execute_and_record(
                        internal_id,
                        chunk_start.date(),
                        chunk_end.date(),
                        trigger="backfill",
                        run_id=run_id,
                    )

            await asyncio.gather(*(_one_chunk(s, e) for s, e in chunks))
        finally:
            await release_backfill_lock(internal_id)

    background_tasks.add_task(_job)

    response = {
        "backfill_id": backfill_id,
        "source_id": _public_id(internal_id),
        "status": "queued",
        "queued_at": now.isoformat(),
        "start": body.start.isoformat(),
        "end": body.end.isoformat(),
        "chunk": body.chunk,
        "concurrency": body.concurrency,
        "deduplicate": body.deduplicate,
        "total_chunks": total_chunks,
        # A rough, undocumented-as-measured estimate (30s/chunk,
        # concurrency-adjusted) -- there's no historical per-chunk
        # duration model to base this on yet.
        "estimated_duration_seconds": round(total_chunks * 30 / body.concurrency),
        "triggered_by": None,  # see /run's own comment on this field
        "progress_url": f"/v1/data-sources/{_public_id(internal_id)}/history?trigger=backfill",
    }
    if idempotency_key:
        await store_idempotent_response(idempotency_key, response)
    log.info(
        "data_sources.backfill_triggered",
        source=internal_id,
        backfill_id=backfill_id,
        total_chunks=total_chunks,
    )
    return response


# ── /health (higher-resolution than the list/one `health` field) ──────

_ERROR_CODE_KEYS = ("missing_credentials", "timeout", "rate_limited", "schema_mismatch")
_ERROR_CODE_PATTERNS: tuple[tuple[str, str], ...] = (
    ("missing_credentials", "api_key"),
    ("missing_credentials", "credential"),
    ("timeout", "timeout"),
    ("rate_limited", "rate limit"),
    ("rate_limited", "429"),
    ("schema_mismatch", "schemaerror"),
    ("schema_mismatch", "validation"),
)


def _classify_error(error: str | None) -> str | None:
    """Best-effort substring classification -- `None` (not a fabricated
    guess) for an error that doesn't match any known pattern; see this
    module's own docstring.
    """
    if not error:
        return None
    lowered = error.lower()
    for code, needle in _ERROR_CODE_PATTERNS:
        if needle in lowered:
            return code
    return None


@router.get("/{source_id}/health")
async def get_data_source_health(source_id: str) -> dict[str, Any]:
    internal_id = _internal_id(source_id)
    if internal_id is None:
        raise _error(404, "not_found", f"no data source with id {source_id!r}")

    cache_key = f"datasources:health:v1:{internal_id}"
    cached = await get_cached(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    settings = get_ingestion_settings()
    override = get_override(internal_id, settings=settings)

    circuit = await _circuit_breaker_state(internal_id)
    consecutive_failures = circuit.get("failures") or 0

    latest_ts = duckdb_store.latest_fetched_at(internal_id)
    freshness_status = "missing"
    if latest_ts is not None:
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)
        age_minutes = (now - latest_ts).total_seconds() / 60
        threshold_minutes = _freshness_threshold_minutes(internal_id, settings)
        freshness_status = "fresh" if age_minutes <= threshold_minutes else "stale"

    status = _health_status(
        enabled=override.enabled,
        freshness_status=freshness_status,
        circuit_state=circuit["state"],
        consecutive_failures=consecutive_failures,
    )

    stats_1h = compute_stats(internal_id, since=now - timedelta(hours=1))
    stats_24h = compute_stats(internal_id, since=now - _DAY)
    stats_7d = compute_stats(internal_id, since=now - _WEEK)
    stats_30d = compute_stats(internal_id, since=now - timedelta(days=30))

    last_5 = list(reversed(read_runs(internal_id)[-5:]))

    error_counts: dict[str, int] = dict.fromkeys(_ERROR_CODE_KEYS, 0)
    for record in read_runs(internal_id, since=now - _DAY):
        if record.status != "failed":
            continue
        code = _classify_error(record.error)
        if code is not None:
            error_counts[code] += 1

    payload = {
        "source_id": _public_id(internal_id),
        "status": status,
        "as_of": now.isoformat(),
        "success_rate_pct_1h": stats_1h.success_rate_pct,
        "success_rate_pct_24h": stats_24h.success_rate_pct,
        "success_rate_pct_7d": stats_7d.success_rate_pct,
        "success_rate_pct_30d": stats_30d.success_rate_pct,
        "p50_duration_ms": stats_7d.p50_duration_ms,
        "p95_duration_ms": stats_7d.p95_duration_ms,
        "p99_duration_ms": stats_7d.p99_duration_ms,
        "consecutive_failures": consecutive_failures,
        "circuit_breaker": {
            "state": circuit["state"],
            "opened_at": circuit.get("opened_at"),
            "half_open_at": circuit.get("half_open_at"),
            "recovery_seconds": circuit.get("recovery_seconds"),
        },
        "last_5_runs": [
            {
                "id": r.run_id,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "records": r.records_inserted,
                "at": r.finished_at,
            }
            for r in last_5
        ],
        "errors_by_code_24h": error_counts,
    }
    await set_cached(cache_key, payload, ttl=10)
    return payload


# ── /history ─────────────────────────────────────────────────────────


def _run_record_to_history_item(record: RunRecord) -> dict[str, Any]:
    return {
        "id": record.run_id,
        "status": record.status,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "duration_ms": record.duration_ms,
        "records_fetched": record.records_fetched,
        "records_inserted": record.records_inserted,
        "duplicates_skipped": None,  # honestly unavailable -- see run_history.py
        "anomalies_flagged": record.anomalies_flagged,
        "trigger": record.trigger,
        "error": record.error,
    }


@router.get("/{source_id}/history")
async def get_data_source_history(
    source_id: str,
    status: Literal["success", "failed", "empty", "partial", "running", "queued"]
    | None = Query(default=None),
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    """Historical run log for one source, most-recent-first,
    cursor-paginated. `status` accepts this repo's own real statuses
    (`success`/`failed`/`empty`) plus the spec's own `partial`/
    `running`/`queued` -- the latter 3 are accepted (never 400) but will
    just never match anything: nothing in this repo currently records a
    run as "partial"/"running"/"queued" in history (only a completed
    run, success/failed/empty, is ever recorded at all).
    """
    internal_id = _internal_id(source_id)
    if internal_id is None:
        raise _error(404, "not_found", f"no data source with id {source_id!r}")

    all_runs = read_runs(internal_id, since=from_)
    if status is not None:
        all_runs = [r for r in all_runs if r.status == status]
    if to is not None:
        all_runs = [r for r in all_runs if datetime.fromisoformat(r.finished_at) <= to]
    all_runs = list(reversed(all_runs))  # most-recent-first

    offset = 0
    if cursor is not None:
        try:
            offset = int(base64.urlsafe_b64decode(cursor.encode()).decode())
        except (ValueError, UnicodeDecodeError):
            raise _error(
                400, "invalid_cursor", f"malformed cursor: {cursor!r}"
            ) from None

    page = all_runs[offset : offset + limit]
    has_more = offset + limit < len(all_runs)
    next_cursor = (
        base64.urlsafe_b64encode(str(offset + limit).encode()).decode()
        if has_more
        else None
    )

    return {
        "source_id": _public_id(internal_id),
        "total": len(all_runs),
        "data": [_run_record_to_history_item(r) for r in page],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


__all__ = ["router"]
