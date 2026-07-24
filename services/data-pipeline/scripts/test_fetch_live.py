"""Live smoke test for OpenElectricityFetcher — hits the real OE API.

Standalone script (not a pytest test): loads OE_API_KEY from .env via
Settings, fetches the current NEM/WEM generation mix, and prints the
normalized rows so you can eyeball real data. Run directly:

    uv run --active ./scripts/test_fetch_live.py
"""

import asyncio
import json

import httpx

from ecolens.config import get_settings
from ecolens.ingestion.sources.openelectricity import OpenElectricityFetcher
from ecolens.shared.observability.logging import get_logger

log = get_logger("test_fetch_live")


async def fetch_live() -> None:
    settings = get_settings()
    if not settings.oe_api_key:
        log.error("oe_api_key.missing", hint="set OE_API_KEY in .env")
        return

    fetcher = OpenElectricityFetcher(api_key=settings.oe_api_key)
    async with httpx.AsyncClient(timeout=settings.oe_request_timeout_seconds) as client:
        results = await fetcher.fetch(client)

    log.info("fetch.complete", row_count=len(results))
    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(fetch_live())
