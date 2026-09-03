"""Per-source admin overrides -- backs `GET`/`PATCH /v1/data-sources/{id}`
(root TODO.md item #2) and `GET /v1/data-sources` (item #1).

Persisted as a small JSON file (`IngestionSettings.data_source_overrides_
path`), not Redis or a new DuckDB table -- same lightweight-state-file
precedent `data/log/warehouse-runs.jsonl`/`warehouse_consumer_status.json`
already set in this codebase, and deliberately more durable than Redis
(which already holds circuit-breaker state, but that's meant to be
ephemeral/self-healing; an admin's "this source is disabled" decision
silently reverting on a Redis restart would be a real regression, not
just a cache miss).

**`enabled` is real, `cron`/`timezone` are not (yet).**
`is_source_enabled()` is called by all 5 `scripts/trigger_ingest_*.py`
at the top of their own `run()` -- setting `enabled=False` genuinely
stops that source's next scheduled fetch. `cron`/`timezone` are
persisted, validated, and returned, but nothing reads them
authoritatively yet: `scripts/cron_ingest_all.sh` still fires every
source from one shared host-crontab entry every 15 minutes (see that
script's own docstring) regardless of any source's stored schedule.
Making the schedule real needs each trigger script (or the cron script
itself) to check "is now within my stored schedule" before running --
a live per-source scheduler, meaningfully bigger scope than persisting
and validating admin-edited fields. Tracked as a real, documented gap,
not silently pretended-away. `next_run_at` (computed by
`api/data_sources_routes.py` via `croniter`, not stored here) is
therefore a *projection* of when a source's stored schedule says it
should next run, not a guarantee anything will actually trigger it.

`version` is an optimistic-concurrency counter over just this
override record (not the whole logical resource, which also includes
live-computed `health`/`last_run` -- those change on their own and
were never meaningful to gate a `PATCH` on). Starts at `1` for a
source that's never been PATCHed; every successful `set_override()`
call increments it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ecolens.ingestion.core.settings import IngestionSettings, get_ingestion_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

# (source key, human label) -- source key matches
# `IngestionSettings.table_for_source()`'s 5 known keys exactly. The one
# canonical list; `data_sources_routes.py` imports this rather than
# keeping its own copy. Richer static metadata (name/category/
# description/url/license/auth/regions) lives in `data_source_catalog.py`,
# not here -- this module is admin-*editable* state, that one is fixed
# fact.
SOURCES: tuple[tuple[str, str], ...] = (
    ("aemo_nem", "AEMO NEM (National Electricity Market)"),
    ("aemo_wem", "AEMO WEM (Wholesale Electricity Market)"),
    ("openelectricity", "OpenElectricity"),
    ("bom", "Bureau of Meteorology (BoM)"),
    ("aemo_holidays", "Public Holidays"),
)
SOURCE_IDS: tuple[str, ...] = tuple(source_id for source_id, _ in SOURCES)
SOURCE_LABELS: dict[str, str] = dict(SOURCES)

# Every fetch (all 5 sources) is triggered by this one host-crontab
# entry -- see scripts/cron_ingest_all.sh's own module docstring. What
# a source's `cron` field reads as until it's explicitly overridden.
DEFAULT_CRON_EXPRESSION = "*/15 * * * *"
DEFAULT_TIMEZONE = "Australia/Sydney"


@dataclass(frozen=True)
class DataSourceOverride:
    enabled: bool = True
    cron: str | None = None  # None -> caller falls back to DEFAULT_CRON_EXPRESSION
    timezone: str = DEFAULT_TIMEZONE
    description: str | None = None  # None -> caller falls back to the catalog default
    auth_type: str | None = None  # None -> caller falls back to the catalog default
    metadata: dict[str, Any] = field(default_factory=dict)
    version: int = 1
    updated_at: str | None = None


def _overrides_path(settings: IngestionSettings | None = None) -> Path:
    settings = settings or get_ingestion_settings()
    return settings.data_source_overrides_path.resolve()


def _read_all(settings: IngestionSettings | None = None) -> dict[str, dict[str, Any]]:
    """`{}` (not an exception) for a missing, empty, or corrupt file --
    every source just falls back to its defaults (enabled, shared cron)
    until an admin actually PATCHes something, and a hand-edited-into-
    invalid-JSON file must degrade, not break every read of this API.
    """
    path = _overrides_path(settings)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("data_source_overrides.read_failed", path=str(path), error=str(exc))
        return {}
    return data if isinstance(data, dict) else {}


def _write_all(
    data: dict[str, dict[str, Any]], settings: IngestionSettings | None = None
) -> None:
    path = _overrides_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def _from_raw(raw: dict[str, Any]) -> DataSourceOverride:
    return DataSourceOverride(
        enabled=raw.get("enabled", True),
        cron=raw.get("cron"),
        timezone=raw.get("timezone", DEFAULT_TIMEZONE),
        description=raw.get("description"),
        auth_type=raw.get("auth_type"),
        metadata=dict(raw.get("metadata", {})),
        version=raw.get("version", 1),
        updated_at=raw.get("updated_at"),
    )


def get_override(
    source_id: str, *, settings: IngestionSettings | None = None
) -> DataSourceOverride:
    return _from_raw(_read_all(settings).get(source_id, {}))


def set_override(
    source_id: str,
    *,
    enabled: bool | None = None,
    cron: str | None = None,
    timezone_name: str | None = None,
    description: str | None = None,
    auth_type: str | None = None,
    metadata: dict[str, Any] | None = None,
    settings: IngestionSettings | None = None,
) -> DataSourceOverride:
    """Merges every non-`None` argument into any existing override for
    `source_id` and persists the result -- PATCH semantics, not a full
    replace, so patching just `enabled` never clobbers a previously-set
    `cron` and vice versa. `metadata`, specifically, *merges keys*
    rather than replacing the whole dict (per the endpoint spec's own
    "does NOT replace" requirement) -- `{**existing, **metadata}`, so
    patching one key never drops the others. Always increments
    `version` by 1 (starting from the *current* stored version, or the
    dataclass default of `1` for a first-ever patch).
    """
    data = _read_all(settings)
    current = dict(data.get(source_id, {}))
    if enabled is not None:
        current["enabled"] = enabled
    if cron is not None:
        current["cron"] = cron
    if timezone_name is not None:
        current["timezone"] = timezone_name
    if description is not None:
        current["description"] = description
    if auth_type is not None:
        current["auth_type"] = auth_type
    if metadata is not None:
        current["metadata"] = {**current.get("metadata", {}), **metadata}
    current["version"] = current.get("version", 1) + 1
    current["updated_at"] = datetime.now(timezone.utc).isoformat()
    data[source_id] = current
    _write_all(data, settings)
    log.info(
        "data_source_overrides.set",
        source=source_id,
        enabled=current.get("enabled"),
        cron=current.get("cron"),
        version=current["version"],
    )
    return _from_raw(current)


def is_source_enabled(
    source_id: str, *, settings: IngestionSettings | None = None
) -> bool:
    """The one function every `scripts/trigger_ingest_*.py` calls at the
    top of its own `run()` -- real enforcement of the `enabled`
    override, not just a stored/returned admin preference.
    """
    return get_override(source_id, settings=settings).enabled


# 5 space-separated fields (minute hour day month weekday), each a `*`,
# a bare number, a number range (`1-5`), an optional `/step`, or a
# comma-separated list of any of those. Syntactic validation only --
# doesn't check field-specific numeric ranges (e.g. minute <= 59) or
# compute actual run times (see `api/data_sources_routes.py`'s
# `croniter` usage for that), just enough to reject obvious garbage
# before it's persisted.
#
# Deliberately NOT the endpoint spec's own literal
# `^(\\*|[0-9,\\-\\/]+)( [0-9,\\-\\/]+){4}$` -- that regex only allows `*`
# in the *first* field; fields 2-5 require `[0-9,\\-\\/]+`, which would
# reject "*/15 * * * *" (this module's own `DEFAULT_CRON_EXPRESSION`)
# and even the spec's own PATCH example (`"*/10 * * * *"`). Treated as
# a documentation artifact, not reproduced here, same as `periods.py`'s
# `previous_period` deviation.
_CRON_PART_RE = re.compile(r"^(\*|[0-9]+(-[0-9]+)?)(/[0-9]+)?$")


def validate_cron_expression(expr: str) -> bool:
    fields = expr.split()
    if len(fields) != 5:
        return False
    return all(
        all(_CRON_PART_RE.match(part) for part in field.split(",")) for field in fields
    )


def validate_timezone(tz: str) -> bool:
    """A real IANA-timezone-database check (stdlib `zoneinfo`, no new
    dependency) -- not a fixed allow-list.
    """
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


__all__ = [
    "SOURCES",
    "SOURCE_IDS",
    "SOURCE_LABELS",
    "DEFAULT_CRON_EXPRESSION",
    "DEFAULT_TIMEZONE",
    "DataSourceOverride",
    "get_override",
    "set_override",
    "is_source_enabled",
    "validate_cron_expression",
    "validate_timezone",
]
