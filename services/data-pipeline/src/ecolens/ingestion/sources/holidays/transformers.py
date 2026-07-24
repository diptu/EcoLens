"""Holiday normalization, Easter computation, synthetic stub, data-quality fixes.

Pure(ish) dict/date transforms — no network I/O (see client.py for
that, cache.py for the local CSV tier). `easter_date` and
`resolve_date` are shared by the synthetic stub; `parse_live_records`
turns data.gov.au's wire records into v1.0 rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ecolens.shared.observability.logging import get_logger

from .schema import (
    HOLIDAY_OUTPUT_COLUMNS,
    NATIONAL_HOLIDAYS,
    REGION_TO_STATE,
    ROLLOVER_HOLIDAYS,
    ROLLOVER_STATES,
    SCHEMA_VERSION,
    STATE_HOLIDAYS,
    STATE_TO_REGIONS,
    VALID_HOLIDAY_TYPES,
    VALID_STATES,
)

log = get_logger(__name__)


def easter_date(year: int) -> date:
    """Anonymous Gregorian algorithm. Returns Easter Sunday as a date.

    Verified: easter_date(2024) = 2024-03-31
              easter_date(2025) = 2025-04-20
              easter_date(2026) = 2026-04-05
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    ll = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * ll) // 451
    month = (h + ll - 7 * m + 114) // 31
    day = ((h + ll - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def resolve_date(md: str, easter: date, year: int) -> date:
    """Resolve a 'MM-DD' or 'easter+N' token to a date."""
    if md.startswith("easter"):
        offset = int(md.replace("easter", ""))
        return easter + timedelta(days=offset)
    month, day = md.split("-")
    return date(year, int(month), int(day))


def build_row(
    *,
    d: date,
    region: str,
    state: str,
    name: str,
    htype: str,
    source: str,
    run_id: str,
    now: datetime,
) -> dict[str, Any]:
    return {
        "date": d.isoformat(),
        "region": region,
        "state": state,
        "holiday_name": name,
        "holiday_type": htype,
        "schema_version": SCHEMA_VERSION,
        "is_business_day": False,
        "is_observed": False,
        "observed_date": None,
        "days_until": None,
        "source": source,
        "ingest_run_id": run_id,
        "fetched_at": now,
    }


def observed_rollovers(
    rows: list[dict[str, Any]],
    run_id: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """When a national holiday falls on a weekend, add an 'observed'
    row for the next Monday (NSW, VIC, SA, WA practice).
    """
    extra: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for r in rows:
        if r["holiday_name"] not in ROLLOVER_HOLIDAYS:
            continue
        if r["state"] not in ROLLOVER_STATES:
            continue
        d = date.fromisoformat(r["date"])
        # If weekend (Sat=5, Sun=6), add Monday
        if d.weekday() in (5, 6):
            observed = d + timedelta(days=(7 - d.weekday()))
            key = (r["region"], observed.isoformat(), r["holiday_name"] + " (observed)")
            if key in seen:
                continue
            seen.add(key)
            # Mark the original as having an observed date
            r["observed_date"] = observed.isoformat()
            r["is_observed"] = False
            extra.append(
                {
                    "date": observed.isoformat(),
                    "region": r["region"],
                    "state": r["state"],
                    "holiday_name": f"{r['holiday_name']} (observed)",
                    "holiday_type": "state",
                    "schema_version": SCHEMA_VERSION,
                    "is_business_day": False,
                    "is_observed": True,
                    "observed_date": observed.isoformat(),
                    "days_until": None,
                    "source": r["source"],
                    "ingest_run_id": run_id,
                    "fetched_at": now,
                }
            )
    return extra


def synthetic_stub(regions: tuple[str, ...], year: int) -> list[dict[str, Any]]:
    """Deterministic stub. NOT for production use.

    Uses the static holiday templates + Easter date computation.
    """
    e = easter_date(year)
    now = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    rows: list[dict[str, Any]] = []

    # National holidays (fanned out to all configured regions)
    for name, md, htype in NATIONAL_HOLIDAYS:
        d = resolve_date(md, e, year)
        for region in regions:
            rows.append(
                build_row(
                    d=d,
                    region=region,
                    state=REGION_TO_STATE[region],
                    name=name,
                    htype=htype,
                    source="synthetic",
                    run_id=run_id,
                    now=now,
                )
            )

    # State-specific holidays
    for state, holidays in STATE_HOLIDAYS.items():
        for name, md, htype in holidays:
            d = resolve_date(md, e, year)
            for region in STATE_TO_REGIONS.get(state, ()):
                if region not in regions:
                    continue
                rows.append(
                    build_row(
                        d=d,
                        region=region,
                        state=state,
                        name=name,
                        htype=htype,
                        source="synthetic",
                        run_id=run_id,
                        now=now,
                    )
                )

    # Observed dates: when a national holiday falls on a weekend,
    # some states (NSW, VIC, SA, WA) observe it on the next Monday.
    rows.extend(observed_rollovers(rows, run_id, now))

    log.warning("holidays.synthetic_stub.used", year=year, rows=len(rows))
    return rows


def parse_live_records(
    records: list[dict[str, Any]],
    year: int,
) -> list[dict[str, Any]]:
    """Parse data.gov.au records into v1.0 rows.

    Expected fields: 'Date' (ISO), 'Name', 'Jurisdiction' (state code)
    """
    out: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    run_id = str(uuid.uuid4())
    for rec in records:
        try:
            rec_year = int(str(rec.get("Date", ""))[:4])
            if rec_year != year:
                continue
            state = str(rec.get("Jurisdiction", "")).upper()
            if state not in VALID_STATES:
                continue
            regions = STATE_TO_REGIONS.get(state, ())
            if not regions:
                continue
            name = str(rec.get("Name", "Unknown")).strip()
            for region in regions:
                out.append(
                    {
                        "date": str(rec.get("Date"))[:10],
                        "region": region,
                        "state": state,
                        "holiday_name": name,
                        "holiday_type": "state",  # data.gov.au doesn't tag this
                        "schema_version": SCHEMA_VERSION,
                        "is_business_day": False,
                        "is_observed": False,
                        "observed_date": None,
                        "days_until": None,
                        "source": "data_gov_au",
                        "ingest_run_id": run_id,
                        "fetched_at": now,
                    }
                )
        except (ValueError, TypeError, KeyError) as exc:
            log.debug("holidays.parse.record_failed", error=str(exc))
            continue
    return out


def apply_data_quality_fixes(
    docs: list[dict[str, Any]],
    year: int,
    regions: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Apply the 5 data quality fixes:

    1. NaN -> None
    2. Region validation (drop unknown regions)
    3. Date normalization to ISO YYYY-MM-DD
    4. Holiday type validation (drop unknown types)
    5. Year filter (drop docs not for the requested year)
    """
    cleaned: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for doc in docs:
        # Fix #1: NaN -> None
        for k, v in list(doc.items()):
            try:
                if isinstance(v, float) and pd.isna(v):
                    doc[k] = None
            except (TypeError, ValueError):
                pass
        # Fix #2: region validation
        region = doc.get("region")
        if region not in regions:
            log.debug("holidays.dq.invalid_region", region=region)
            continue
        # Fix #3: date normalization
        raw_date = doc.get("date")
        if raw_date is None:
            continue
        try:
            d = date.fromisoformat(str(raw_date)[:10])
            doc["date"] = d.isoformat()
        except (ValueError, TypeError):
            log.debug("holidays.dq.bad_date", raw=raw_date)
            continue
        # Fix #4: holiday type validation
        htype = doc.get("holiday_type", "state")
        if htype not in VALID_HOLIDAY_TYPES:
            doc["holiday_type"] = "state"  # normalize unknown
        # Fix #5: year filter
        if d.year != year:
            continue
        # Dedupe (region, date) -- keep LAST occurrence
        key = (doc["region"], doc["date"])
        if key in seen:
            # Replace earlier doc with this one
            cleaned = [c for c in cleaned if (c["region"], c["date"]) != key]
        seen.add(key)
        # Ensure all schema columns present
        for col in HOLIDAY_OUTPUT_COLUMNS:
            doc.setdefault(col, None)
        cleaned.append(doc)
    return cleaned


def attach_days_until(docs: list[dict[str, Any]], today: date) -> None:
    """Set `days_until` on each doc (in-place)."""
    for d in docs:
        try:
            doc_date = date.fromisoformat(d["date"])
            d["days_until"] = (doc_date - today).days
        except (ValueError, KeyError, TypeError):
            d["days_until"] = None


def diagnose(docs: list[dict[str, Any]]) -> None:
    """Log per-region and per-type coverage stats."""
    if not docs:
        log.warning("holidays.diagnose.empty")
        return
    df = pd.DataFrame(docs)
    per_region = df["region"].value_counts().to_dict()
    per_type = df["holiday_type"].value_counts().to_dict()
    log.info(
        "holidays.diagnose.complete",
        rows=len(docs),
        per_region=per_region,
        per_type=per_type,
    )
