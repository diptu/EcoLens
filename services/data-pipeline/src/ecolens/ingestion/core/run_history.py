"""Per-run history for the 5 live ingestion sources -- backs `GET
/v1/data-sources[/{id}]`'s `last_run` and `health.success_rate_pct_*`/
`p50/p95/p99_duration_ms` fields with real, measured data instead of
numbers nobody ever tracked. Before this module, none of that existed
anywhere: `scripts/trigger_ingest_*.py` only ever logged to the
structured logger (not a queryable store), and `CircuitBreaker` only
ever tracked a live failure *count*, never individual run outcomes or
durations.

Same append-only JSONL pattern `warehouse/service/metrics.py`'s
`MetricsEmitter` already established for `warehouse-runs.jsonl` --
`IngestionSettings.ingestion_runs_log_path`
(`data/log/ingestion-runs.jsonl` by default), one JSON line per
completed `scripts/trigger_ingest_*.py` run (success or failure),
tailable by promtail/vector -> Loki like that file already is.

`duplicates_skipped` from the KPI spec's `last_run` shape is
deliberately **not** a field here: `duckdb_store.write_historical()`'s
upsert can't currently distinguish "inserted a genuinely new row" from
"overwrote an existing one with the same/updated values" -- its return
value is docs *processed*, not docs *newly inserted*. Reporting a
fabricated duplicate count would be worse than omitting the field;
making it real needs `_upsert()` itself instrumented to diff before/after
row counts, out of scope for this module.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from ecolens.ingestion.core.settings import IngestionSettings, get_ingestion_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    source: str
    # "success" (wrote >=1 record) | "failed" (an actual error --
    # `error` is set) | "empty" (fetch ran clean but returned zero
    # rows, e.g. an AEMO archive month not published yet -- a genuinely
    # expected outcome for some call patterns, not a failure; see
    # `compute_stats`' own docstring for how this counts toward
    # `success_rate_pct`).
    status: str
    started_at: str  # ISO 8601
    finished_at: str  # ISO 8601
    duration_ms: float
    records_fetched: int | None = None
    records_inserted: int | None = None
    anomalies_flagged: int | None = None
    error: str | None = None
    # "schedule" (the 5 scripts/trigger_ingest_*.py's own default, fired
    # by cron) | "manual" (POST .../run) | "backfill" (POST .../backfill)
    # -- "retry"/"dependency" from the endpoint spec's own enum aren't
    # produced by anything in this repo yet (no DLQ, no cross-source
    # trigger chaining), so they're valid values to *read* but nothing
    # ever writes them.
    trigger: str = "schedule"


@dataclass(frozen=True)
class RunStats:
    """`None` fields (not `0`/fabricated) when `n_runs == 0` -- "no runs
    recorded in this window" is a different, honest state from "0%
    success rate."
    """

    success_rate_pct: float | None
    p50_duration_ms: float | None
    p95_duration_ms: float | None
    p99_duration_ms: float | None
    n_runs: int


def _log_path(settings: IngestionSettings | None = None) -> Path:
    settings = settings or get_ingestion_settings()
    return settings.ingestion_runs_log_path.resolve()


def record_run(
    source: str,
    *,
    status: str,
    started_at: datetime,
    finished_at: datetime,
    records_fetched: int | None = None,
    records_inserted: int | None = None,
    anomalies_flagged: int | None = None,
    error: str | None = None,
    run_id: str | None = None,
    trigger: str = "schedule",
    settings: IngestionSettings | None = None,
) -> RunRecord:
    record = RunRecord(
        run_id=run_id or uuid.uuid4().hex,
        source=source,
        status=status,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        duration_ms=round((finished_at - started_at).total_seconds() * 1000, 1),
        records_fetched=records_fetched,
        records_inserted=records_inserted,
        anomalies_flagged=anomalies_flagged,
        error=error,
        trigger=trigger,
    )
    path = _log_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(asdict(record)) + "\n")
    log.info(
        "ingestion_runs.recorded",
        source=source,
        status=status,
        duration_ms=record.duration_ms,
    )
    return record


def read_runs(
    source: str | None = None,
    *,
    since: datetime | None = None,
    settings: IngestionSettings | None = None,
) -> list[RunRecord]:
    """Every recorded run, optionally filtered to one `source` and/or
    `since` a cutoff -- `[]` (not an exception) for a missing file or a
    corrupt individual line, same resilience convention
    `core/data_source_overrides.py` already establishes: one bad line
    (e.g. a crash mid-write) must never break every read of this
    history, it just gets skipped.
    """
    path = _log_path(settings)
    if not path.exists():
        return []
    records: list[RunRecord] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if source is not None and raw.get("source") != source:
            continue
        if since is not None:
            try:
                finished = datetime.fromisoformat(raw["finished_at"])
            except (KeyError, ValueError):
                continue
            if finished < since:
                continue
        try:
            records.append(RunRecord(**raw))
        except TypeError:
            continue  # a line from an incompatible/older schema version
    return records


def last_run(
    source: str, *, settings: IngestionSettings | None = None
) -> RunRecord | None:
    runs = read_runs(source, settings=settings)
    return runs[-1] if runs else None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (pct / 100)
    lower, upper = int(k), min(int(k) + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (k - lower)


def compute_stats(
    source: str, *, since: datetime, settings: IngestionSettings | None = None
) -> RunStats:
    """`success_rate_pct` counts `"empty"` runs as non-failures (an
    empty-but-clean fetch isn't an error) alongside `"success"` --
    only `"failed"` runs count against it.
    """
    runs = read_runs(source, since=since, settings=settings)
    if not runs:
        return RunStats(None, None, None, None, 0)
    successes = sum(1 for r in runs if r.status != "failed")
    durations = [r.duration_ms for r in runs]
    return RunStats(
        success_rate_pct=round(successes / len(runs) * 100, 1),
        p50_duration_ms=_percentile(durations, 50),
        p95_duration_ms=_percentile(durations, 95),
        p99_duration_ms=_percentile(durations, 99),
        n_runs=len(runs),
    )


__all__ = [
    "RunRecord",
    "RunStats",
    "record_run",
    "read_runs",
    "last_run",
    "compute_stats",
]
