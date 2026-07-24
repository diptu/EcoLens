"""HTTP client for the data.gov.au public holidays dataset.

Owns all network I/O: hits the data.gov.au datastore_search API and
decodes the wire JSON into v1.0 rows via
`transformers.parse_live_records`. Does not apply data-quality fixes
or handle the cache/synthetic fallback tiers — see `engine.py` for that.

Retries (`ingest_max_retries`/`ingest_retry_backoff_base`) and circuit
breaker protection are both driven by the shared
`ecolens.ingestion.circuit_breaker` module -- see ECO-101. The breaker
is optional (defaults to None) so existing zero-arg construction, and
every test that relies on it, keeps working without a live Redis
instance; `engine.py` wires one in when a real one is available.
"""

from __future__ import annotations

from typing import Any

import httpx

from ecolens.ingestion.circuit_breaker import CircuitBreaker, retry_with_backoff
from ecolens.ingestion.storage.settings import MongoSettings, get_mongo_settings
from ecolens.shared.observability.logging import get_logger

from .schema import DATA_GOV_AU_BASE, DATA_GOV_AU_DATASET, TIMEOUT_SECONDS
from .transformers import parse_live_records

log = get_logger(__name__)


class HolidayClient:
    """Fetch the data.gov.au combined public-holidays dataset for one year."""

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

    async def fetch_year(
        self,
        client: httpx.AsyncClient,
        year: int,
    ) -> list[dict[str, Any]] | None:
        """Try the data.gov.au combined dataset.

        Returns None if the request fails (after retries) or returns no
        records (caller falls back to cache).
        """

        async def _do_fetch() -> dict[str, Any]:
            url = (
                f"{DATA_GOV_AU_BASE}/datastore_search"
                f"?resource_id={DATA_GOV_AU_DATASET}&limit=200"
            )
            response = await client.get(
                url,
                timeout=TIMEOUT_SECONDS,
                headers={"User-Agent": "ecoLens/0.2.0"},
            )
            response.raise_for_status()
            return response.json()

        try:
            if self.circuit_breaker is not None:
                await self.circuit_breaker.before_call()
            payload = await retry_with_backoff(
                _do_fetch,
                max_retries=self.max_retries,
                backoff_base=self.backoff_base,
                on_retry=lambda attempt, exc, delay: log.warning(
                    "holidays.api.retry", attempt=attempt, error=str(exc), sleep=delay
                ),
            )
        except Exception as exc:  # noqa: BLE001
            if self.circuit_breaker is not None:
                await self.circuit_breaker.record_failure()
            log.warning("holidays.api.failed", error=str(exc))
            return None
        if self.circuit_breaker is not None:
            await self.circuit_breaker.record_success()
        records = payload.get("result", {}).get("records", [])
        if not records:
            return None
        return parse_live_records(records, year)
