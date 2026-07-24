"""HTTP client for the AEMO WEM data portal (data.wa.aemo.com.au).

Owns all network I/O across three independent WEMDE feeds:
  - facilityScada: 5-min per-facility generation (MW)
  - operationalDemandWithdrawal: 5-min system demand (MW)
  - referenceTradingPrice: 30-min reference trading price ($/MWh)

Confirmed against live data (2026-07): unlike NEM's single unpredictable-
filename zip, WEM filenames are predictable — `{Prefix}_{YYYY-MM-DD}.json`
under `current/` for the last day or two, falling back to
`{Prefix}_{YYYYMMDD}.zip` under `previous/` for older days (the zip
contains one JSON file, same shape, named with hyphens). Demand has no
current/previous split at all — one flat directory holds full history
as plain JSON, no zips.

Retries (`ingest_max_retries`/`ingest_retry_backoff_base`) wrap each
individual feed request; circuit breaker protection (optional, see
ECO-101) wraps the whole `fetch_day_data` call so a transient failure
on one feed doesn't retry the other two, but the breaker still reflects
"is this whole source down" rather than one feed's hiccup.
"""

from __future__ import annotations

import json
import zipfile
from datetime import date
from io import BytesIO

import httpx

from ecolens.ingestion.circuit_breaker import CircuitBreaker, retry_with_backoff
from ecolens.ingestion.storage.settings import MongoSettings, get_mongo_settings
from ecolens.shared.observability.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://data.wa.aemo.com.au/public/market-data/wemde"
TIMEOUT_SECONDS = 60.0


class AEMOWEMClient:
    """Fetch one day's raw WEM SCADA/demand/price records."""

    def __init__(
        self,
        *,
        settings: MongoSettings | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        settings = settings or get_mongo_settings()
        self.max_retries = settings.ingest_max_retries
        self.backoff_base = settings.ingest_retry_backoff_base
        self.circuit_breaker = circuit_breaker

    async def fetch_day_data(
        self,
        client: httpx.AsyncClient,
        day: date,
    ) -> dict[str, list[dict]] | None:
        """Download one AWST day's SCADA, demand, and price feeds.

        Returns None if the primary feed (facilityScada) hasn't been
        published yet for `day` — mirrors AEMONEMClient's "day not
        published" signal. Demand/price missing individually (rare;
        the three feeds don't always land at the same time) just
        yields an empty list for that feed rather than failing the
        whole day.
        """

        async def _impl() -> dict[str, list[dict]] | None:
            # The `previous/` zip filename prefix doesn't always match
            # the `current/` JSON prefix — confirmed live: facilityScada's
            # zip is `FacilityScada_{date}.zip` even though the JSON
            # inside (and current/'s own JSON) is `SCADA_{date}.json`.
            scada = await self._fetch_with_fallback(
                client, "facilityScada", "SCADA", "FacilityScada", day
            )
            if scada is None:
                return None
            demand = await self._fetch_demand(client, day)
            price = await self._fetch_with_fallback(
                client,
                "referenceTradingPrice",
                "ReferenceTradingPrice",
                "ReferenceTradingPrice",
                day,
            )

            return {
                "scada": scada.get("data", {}).get(
                    "facilityScadaDispatchIntervals", []
                ),
                "demand": demand.get("data", {}).get("data", []) if demand else [],
                "price": (price or {})
                .get("data", {})
                .get("referenceTradingPrices", []),
            }

        if self.circuit_breaker is not None:
            return await self.circuit_breaker.call(_impl)
        return await _impl()

    async def _fetch_demand(self, client: httpx.AsyncClient, day: date) -> dict | None:
        # No current/previous split — one flat directory, full history.
        url = f"{BASE_URL}/operationalDemandWithdrawal/dailyFiles/OperationalDemandAndWithdrawal_{day.isoformat()}.json"
        return await self._get_json(client, url)

    async def _fetch_with_fallback(
        self,
        client: httpx.AsyncClient,
        feed_dir: str,
        json_prefix: str,
        zip_prefix: str,
        day: date,
    ) -> dict | None:
        current_url = (
            f"{BASE_URL}/{feed_dir}/current/{json_prefix}_{day.isoformat()}.json"
        )
        body = await self._get_json(client, current_url)
        if body is not None:
            return body

        # Fall back to the zipped archive (older days roll out of
        # `current/` after a day or two).
        previous_url = (
            f"{BASE_URL}/{feed_dir}/previous/{zip_prefix}_{day.strftime('%Y%m%d')}.zip"
        )
        zip_bytes = await self._get_bytes(client, previous_url)
        if zip_bytes is None:
            return None
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            if not names:
                return None
            return json.loads(zf.read(names[0]).decode("utf-8"))

    async def _get_json(self, client: httpx.AsyncClient, url: str) -> dict | None:
        async def _do_get() -> dict | None:
            response = await client.get(url, timeout=TIMEOUT_SECONDS)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.json()

        return await retry_with_backoff(
            _do_get,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
            on_retry=lambda attempt, exc, delay: log.warning(
                "aemo_wem.api.retry",
                url=url,
                attempt=attempt,
                error=str(exc),
                sleep=delay,
            ),
        )

    async def _get_bytes(self, client: httpx.AsyncClient, url: str) -> bytes | None:
        async def _do_get() -> bytes | None:
            response = await client.get(url, timeout=TIMEOUT_SECONDS)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return response.content

        return await retry_with_backoff(
            _do_get,
            max_retries=self.max_retries,
            backoff_base=self.backoff_base,
            on_retry=lambda attempt, exc, delay: log.warning(
                "aemo_wem.api.retry",
                url=url,
                attempt=attempt,
                error=str(exc),
                sleep=delay,
            ),
        )
