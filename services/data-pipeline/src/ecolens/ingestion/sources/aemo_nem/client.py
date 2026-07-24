"""HTTP client for the NEMWeb public archive.

Owns all network I/O: resolves the day's zip URL from the directory
listing, downloads it, and decodes the AEMO MMS multi-table CSV inside
into raw per-table DataFrames (deduped, but not yet reshaped into the
canonical fueltech/region columns — see `transformers.py` for that).
"""

from __future__ import annotations

import asyncio
import csv
import io
import re
import zipfile
from datetime import datetime

import httpx
import pandas as pd

from ecolens.shared.observability.logging import get_logger

from .schema import TABLE_NATURAL_KEYS

log = get_logger(__name__)

NEMWEB_BASE = "https://www.nemweb.com.au/Reports/Current/Daily_Reports/"
NEMWEB_ARCHIVE_BASE = "https://www.nemweb.com.au/Reports/Archive/Historical_Reports/"
NEMWEB_HOST = "https://www.nemweb.com.au"
TIMEOUT_SECONDS = 60.0
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5

USER_AGENT_HEADERS = {"User-Agent": "ecoLens/0.2.0 (https://github.com/diptu/ecoLens)"}

# Tables this client decodes out of every PUBLIC_DAILY file.
WANTED_TABLES: frozenset[str] = frozenset({"DUNIT", "DREGION"})


class AEMONEMClient:
    """Fetch one day's raw AEMO MMS tables (DUNIT, DREGION) from NEMWeb."""

    async def fetch_day_tables(
        self,
        client: httpx.AsyncClient,
        day: datetime,
    ) -> dict[str, pd.DataFrame] | None:
        """Download + decode one day's PUBLIC_DAILY zip.

        Returns None if that day hasn't been published yet (files land
        ~4am the following day). Otherwise returns `{"DUNIT": df,
        "DREGION": df}`, each already deduped on its natural key.
        """
        url = await self._resolve_day_url(client, day)
        if url is None:
            return None
        zip_bytes = await self._download_zip(client, url)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            raw = zf.read(zf.namelist()[0]).decode("utf-8-sig")
        return self._parse_mms_tables(raw, WANTED_TABLES)

    async def _resolve_day_url(
        self, client: httpx.AsyncClient, day: datetime
    ) -> str | None:
        """Find the real PUBLIC_DAILY zip URL for `day` from the NEMWeb
        directory listing — the filename embeds an unpredictable publish
        timestamp (e.g. PUBLIC_DAILY_202607190000_20260720040503.zip),
        so it can't be constructed from a fixed pattern.
        """
        response = await client.get(
            NEMWEB_BASE, timeout=TIMEOUT_SECONDS, headers=USER_AGENT_HEADERS
        )
        response.raise_for_status()
        pattern = re.compile(
            r'HREF="([^"]*PUBLIC_DAILY_' + day.strftime("%Y%m%d") + r'0000_\d+\.zip)"',
            re.IGNORECASE,
        )
        match = pattern.search(response.text)
        if match is None:
            return None
        href = match.group(1)
        return href if href.startswith("http") else f"{NEMWEB_HOST}{href}"

    async def _download_zip(self, client: httpx.AsyncClient, url: str) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log.info("aemo_nem.zip.download", url=url, attempt=attempt)
                response = await client.get(
                    url, timeout=TIMEOUT_SECONDS, headers=USER_AGENT_HEADERS
                )
                response.raise_for_status()
                return response.content
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
            if attempt < MAX_RETRIES:
                sleep_s = RETRY_BACKOFF_BASE**attempt
                log.warning(
                    "aemo_nem.zip.retry",
                    url=url,
                    attempt=attempt,
                    sleep=sleep_s,
                    error=str(last_exc),
                )
                await asyncio.sleep(sleep_s)
        if (
            last_exc is None
        ):  # pragma: no cover - loop always sets it before falling through
            raise RuntimeError(
                f"Exhausted retries for {url} with no captured exception"
            )
        raise last_exc

    @staticmethod
    def _parse_mms_tables(raw: str, wanted: frozenset[str]) -> dict[str, pd.DataFrame]:
        """Parse an AEMO MMS multi-table CSV into DataFrames for `wanted` tables.

        Confirmed against a live PUBLIC_DAILY file — NOT the classic
        one-table-per-CSV NEMWeb format. The whole zip is a single CSV:
        `I,<table>,<subtable>,<version>,<col>,...` rows define a
        table's header; every `D,<table>,<subtable>,...` row that
        follows (until the next `I,` row) is that table's data.
        """
        headers: dict[str, list[str]] = {}
        rows: dict[str, list[list[str]]] = {name: [] for name in wanted}
        for parts in csv.reader(raw.splitlines()):
            if len(parts) < 3:
                continue
            record_type, table = parts[0], parts[1]
            if record_type == "I" and table in wanted:
                headers[table] = parts[4:]
            elif record_type == "D" and table in wanted:
                rows[table].append(parts[4:])

        result: dict[str, pd.DataFrame] = {}
        for table in wanted:
            cols = headers.get(table)
            data = rows.get(table, [])
            if not cols or not data:
                result[table] = pd.DataFrame()
                continue
            width = len(cols)
            trimmed = [r[:width] + [None] * (width - len(r)) for r in data]
            df = pd.DataFrame(trimmed, columns=cols)
            # Confirmed against a live file: PUBLIC_DAILY bundles two
            # full copies of both DUNIT and DREGION (same natural key,
            # identical values). Left undeduped, pivot_table(aggfunc=
            # "sum") downstream would silently double-count every
            # generation value.
            key_cols = [c for c in TABLE_NATURAL_KEYS.get(table, []) if c in df.columns]
            if key_cols:
                df = df.drop_duplicates(subset=key_cols, keep="first")
            result[table] = df
        return result
