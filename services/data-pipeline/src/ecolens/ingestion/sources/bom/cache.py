"""Local CSV cache tier for BoM observations.

Dev/CI fallback when the live BoM API is unreachable: `read_cache`
reads whatever has previously been written by `write_cache`, deduped
on (region, ts, station_id). Not used in the live/synthetic tiers —
see `engine.py` for the tier selection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)


def read_cache(
    cache_dir: Path,
    since: Any,
    until: Any,
) -> list[dict[str, Any]]:
    if not cache_dir.exists():
        return []
    frames: list[pd.DataFrame] = []
    for path in cache_dir.glob("observations_*.csv"):
        try:
            df = pd.read_csv(path, parse_dates=["ts"])
        except Exception as exc:  # noqa: BLE001
            log.warning("bom.cache.read_failed", path=str(path), error=str(exc))
            continue
        frames.append(df)
    if not frames:
        return []
    out = pd.concat(frames, ignore_index=True)
    if out["ts"].dt.tz is None:
        out["ts"] = out["ts"].dt.tz_localize("UTC")
    else:
        out["ts"] = out["ts"].dt.tz_convert("UTC")
    # Force station_id back to string (CSV round-trip converts to int)
    if "station_id" in out.columns:
        out["station_id"] = out["station_id"].astype(str).str.zfill(6)
    # Force schema_version back to string (CSV round-trip infers the
    # all-numeric-looking "1.0" as float64)
    if "schema_version" in out.columns:
        out["schema_version"] = out["schema_version"].astype(str)
    out = out[(out["ts"] >= since) & (out["ts"] <= until)]
    return out.to_dict("records")


def write_cache(
    cache_dir: Path,
    docs: list[dict[str, Any]],
    *,
    region: str | None = None,
) -> list[Path]:
    """Persist a batch of docs to the local cache.

    Writes one CSV per (region, date) under cache_dir. Returns the
    list of paths written. Called by the ingest task after a
    successful live fetch.
    """
    if not docs:
        return []
    df = pd.DataFrame(docs)
    if df["ts"].dt.tz is None:
        df["ts"] = df["ts"].dt.tz_localize("UTC")
    df["date"] = df["ts"].dt.tz_convert("UTC").dt.strftime("%Y%m%d")
    written: list[Path] = []
    for (reg, date), group in df.groupby(["region", "date"]):
        if region and reg != region:
            continue
        path = cache_dir / f"observations_{reg}_{date}.csv"
        if path.exists():
            existing = pd.read_csv(path, parse_dates=["ts"])
            if existing["ts"].dt.tz is None:
                existing["ts"] = existing["ts"].dt.tz_localize("UTC")
            else:
                existing["ts"] = existing["ts"].dt.tz_convert("UTC")
            # Force station_id to string (CSV round-trip converts to int)
            existing["station_id"] = existing["station_id"].astype(str).str.zfill(6)
            # Force schema_version to string (CSV round-trip infers the
            # all-numeric-looking "1.0" as float64)
            if "schema_version" in existing.columns:
                existing["schema_version"] = existing["schema_version"].astype(str)
            combined = pd.concat([existing, group], ignore_index=True)
            combined = combined.drop_duplicates(
                subset=["region", "ts", "station_id"], keep="last"
            )
        else:
            combined = group
        combined.to_csv(path, index=False)
        written.append(path)
    log.info("bom.cache.written", files=len(written))
    return written
