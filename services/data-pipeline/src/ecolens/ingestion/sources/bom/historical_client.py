"""HTTP client for the Open-Meteo historical (ERA5) archive API.

Owns all network I/O: hits `archive-api.open-meteo.com`, decodes the
wire JSON, and normalizes it into v1.0 rows via
`historical_transformers.parse_open_meteo_response`. Chunking a wide
date range into <=365-day pieces (Open-Meteo's per-request limit) is
handled by `historical.py`'s orchestration layer, not here.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

import httpx

from ecolens.shared.observability.logging import get_logger

from .schema import (
    BOM_USER_AGENT,
    HISTORICAL_TIMEOUT_SECONDS,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
)
from .historical_transformers import build_open_meteo_url, parse_open_meteo_response

log = get_logger(__name__)


class OpenMeteoClient:
    """Fetch one (region, date-range) chunk from Open-Meteo, with retries."""

    async def fetch_chunk(
        self,
        client: httpx.AsyncClient,
        region: str,
        start: datetime,
        end: datetime,
        stations: dict[str, str],
    ) -> list[dict[str, Any]] | None:
        """Fetch and parse one chunk. Returns None if the request ultimately failed."""
        url = build_open_meteo_url(region, start, end)
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log.info(
                    "bom_historical.fetch",
                    region=region,
                    attempt=attempt,
                    start=start.date().isoformat(),
                    end=end.date().isoformat(),
                )
                response = await client.get(
                    url,
                    timeout=HISTORICAL_TIMEOUT_SECONDS,
                    headers={"User-Agent": BOM_USER_AGENT},
                )
                response.raise_for_status()
                payload = response.json()
                return parse_open_meteo_response(payload, region, stations)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
            if attempt < MAX_RETRIES:
                sleep_s = RETRY_BACKOFF_BASE**attempt
                log.warning(
                    "bom_historical.retry",
                    region=region,
                    attempt=attempt,
                    sleep=sleep_s,
                    error=str(last_exc),
                )
                await asyncio.sleep(sleep_s)
        log.error("bom_historical.failed", region=region, error=str(last_exc))
        return None


__all__ = ["OpenMeteoClient"]
