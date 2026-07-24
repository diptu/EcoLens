"""Local CSV cache tier for public holidays.

Dev/CI fallback when the live data.gov.au API is unreachable:
`read_cache` reads whatever `write_cache` previously wrote, one CSV
per (region, year), deduped on (region, date). Not used in the live/
synthetic tiers — see `engine.py` for the tier selection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)


def read_cache(
    cache_dir: Path, regions: tuple[str, ...], year: int
) -> list[dict[str, Any]]:
    if not cache_dir.exists():
        return []
    frames: list[pd.DataFrame] = []
    for region in regions:
        path = cache_dir / f"holidays_{region}_{year}.csv"
        if not path.exists():
            continue
        try:
            df = pd.read_csv(path)
            frames.append(df)
        except Exception as exc:  # noqa: BLE001
            log.warning("holidays.cache.read_failed", path=str(path), error=str(exc))
    if not frames:
        return []
    out = pd.concat(frames, ignore_index=True)
    return out.to_dict("records")


def write_cache(
    cache_dir: Path,
    docs: list[dict[str, Any]],
    *,
    year: int,
) -> list[Path]:
    """Persist docs to cache, one CSV per (region, year)."""
    if not docs:
        return []
    df = pd.DataFrame(docs)
    written: list[Path] = []
    for region, group in df.groupby("region"):
        path = cache_dir / f"holidays_{region}_{year}.csv"
        if path.exists():
            existing = pd.read_csv(path)
            combined = pd.concat([existing, group], ignore_index=True)
            combined = combined.drop_duplicates(subset=["region", "date"], keep="last")
        else:
            combined = group
        combined.to_csv(path, index=False)
        written.append(path)
    log.info("holidays.cache.written", files=len(written), year=year)
    return written
