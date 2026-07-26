"""HTTP client for the BoM public v1 observations API.

Owns all network I/O: hits
`api.weather.bom.gov.au/v1/locations/{geohash}/observations` with
retries, decodes the wire JSON, and normalizes it into a v1.0 row via
`transformers.normalize_observation`. Does not apply data-quality
fixes or handle the cache/synthetic fallback tiers — see `engine.py`
for that.

Unlike the legacy `/fwo/{station_id}/observations.json` endpoint this
replaces (404s since BoM's 2024 migration), the v1 endpoint returns
exactly ONE current observation per call — no history, no date-range
params. `since`/`until` are still accepted (matching the legacy
signature engine.py calls this with) but only ever include or exclude
that single observation, never select from a range.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import httpx
import pandas as pd

from ecolens.shared.observability.logging import get_logger

from .schema import (
    BOM_BASE_URL,
    BOM_LOCATIONS_PATH,
    BOM_OBSERVATIONS_PATH,
    BOM_USER_AGENT,
    MAX_RETRIES,
    RETRY_BACKOFF_BASE,
    TIMEOUT_SECONDS,
)
from .transformers import normalize_observation

log = get_logger(__name__)


class BomClient:
    """Fetch one station's current observation (by geohash), with retries."""

    async def fetch_station(
        self,
        client: httpx.AsyncClient,
        region: str,
        geohash: str,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]]:
        url = f"{BOM_BASE_URL}{BOM_LOCATIONS_PATH}/{geohash}{BOM_OBSERVATIONS_PATH}"
        last_exc: Exception | None = None
        raw_text: str | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                log.info(
                    "bom.api.fetch", region=region, geohash=geohash, attempt=attempt
                )
                response = await client.get(
                    url,
                    timeout=TIMEOUT_SECONDS,
                    headers={"User-Agent": BOM_USER_AGENT},
                )
                response.raise_for_status()
                raw_text = response.text
                break
            except Exception as exc:  # httpx errors + decode errors
                last_exc = exc
            if attempt < MAX_RETRIES:
                sleep_s = RETRY_BACKOFF_BASE**attempt
                log.warning(
                    "bom.api.retry",
                    region=region,
                    attempt=attempt,
                    sleep=sleep_s,
                    error=str(last_exc),
                )
                await asyncio.sleep(sleep_s)
        if raw_text is None:
            if last_exc is None:  # pragma: no cover - defensive, loop always sets it
                raise RuntimeError("fetch_station retry loop exited without an error")
            raise last_exc
        return self.parse_observation_json(raw_text, region, geohash, since, until)

    def parse_observation_json(
        self,
        raw_text: str,
        region: str,
        geohash: str,
        since: datetime,
        until: datetime,
    ) -> list[dict[str, Any]]:
        try:
            payload = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            log.warning("bom.parse.json_failed", region=region, error=str(exc))
            return []
        if not payload.get("data"):
            return []
        now = pd.Timestamp.now(tz="UTC")
        row = normalize_observation(payload, region, geohash, now)
        if row is None:
            return []
        ts = row["ts"]
        if ts < since or ts > until:
            return []
        return [row]
