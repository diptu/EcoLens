"""Static, factual metadata about each of the 5 real ingestion sources
-- name, category, description, upstream URL, license, and auth
requirement. Distinct from `data_source_overrides.py` (mutable admin
state: enabled/cron/description-override/metadata) -- this file is the
factual baseline an override, well, overrides.

`url` values are the actual upstream endpoints each fetcher's own
client module calls (`ingestion/service/*/client.py`'s own `BASE_URL`/
equivalent constants), verified against that code, not guessed --
except `aemo_nem`'s, which uses the human-readable AEMO data-portal
page rather than the raw NEMWeb report-listing URL, matching how it
was already given in the endpoint spec this catalog implements.

`license` values are a good-faith summary of each publisher's general
open-data posture, not a verified legal opinion -- confirm against the
publisher's current terms before treating this as authoritative for
compliance purposes. `bom`'s is deliberately phrased as a plain
copyright notice, not a specific Creative Commons version, since
unlike the other 4 (all clearly CC BY 4.0-equivalent Australian
open-data conventions) BoM's exact current reuse terms weren't
confidently verifiable while writing this.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DataSourceInfo:
    id: str
    name: str
    category: str  # "grid" | "weather" | "carbon" | "fuel" | "custom"
    description: str
    url: str
    license: str
    auth_type: str  # "none" | "api_key"
    regions: tuple[str, ...]


_ENTRIES: tuple[DataSourceInfo, ...] = (
    DataSourceInfo(
        id="aemo_nem",
        name="AEMO NEM",
        category="grid",
        description=(
            "Australian Energy Market Operator — National Electricity "
            "Market (NSW1, QLD1, VIC1, SA1, TAS1): dispatch demand, "
            "price, and generation-mix data at 5-minute/30-minute "
            "granularity."
        ),
        url="https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem",
        license="CC BY 4.0",
        auth_type="none",
        regions=("NSW1", "QLD1", "VIC1", "SA1", "TAS1"),
    ),
    DataSourceInfo(
        id="aemo_wem",
        name="AEMO WEM",
        category="grid",
        description=(
            "Australian Energy Market Operator — Wholesale Electricity "
            "Market (Western Australia): WEMDE dispatch demand, price, "
            "and generation-mix data, single-zone (no NEM-style "
            "sub-regions)."
        ),
        url="https://data.wa.aemo.com.au/public/market-data/wemde",
        license="CC BY 4.0",
        auth_type="none",
        regions=("WEM",),
    ),
    DataSourceInfo(
        id="openelectricity",
        name="OpenElectricity",
        category="grid",
        description=(
            "Community-maintained aggregation of NEM + WEM generation by "
            "fuel type — used as a fallback/cross-check source for "
            "regions and columns AEMO's own per-region feeds don't cover "
            "directly (e.g. NEM's broadcast fuel-tech mix)."
        ),
        url="https://api.openelectricity.org.au/v4/data/network",
        license="CC BY 4.0",
        auth_type="api_key",
        regions=("NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"),
    ),
    DataSourceInfo(
        id="bom",
        name="Bureau of Meteorology (BoM)",
        category="weather",
        description=(
            "Australian Government Bureau of Meteorology weather "
            "observations (temperature, humidity, wind, rain) for the 6 "
            "default NEM/WEM station locations; falls back to Open-Meteo "
            "ERA5 reanalysis for historical backfill beyond BoM's own "
            "~72-hour live window."
        ),
        url="https://api.weather.bom.gov.au",
        license="© Commonwealth of Australia, Bureau of Meteorology",
        auth_type="none",
        regions=(),
    ),
    DataSourceInfo(
        id="aemo_holidays",
        name="Public Holidays",
        category="custom",
        description=(
            "Australian public holidays by state/region, from the "
            "data.gov.au combined public-holidays dataset — feeds the "
            "demand model's is_public_holiday feature."
        ),
        url="https://data.gov.au",
        license="CC BY 4.0",
        auth_type="none",
        regions=("NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"),
    ),
)

CATALOG: dict[str, DataSourceInfo] = {info.id: info for info in _ENTRIES}

__all__ = ["DataSourceInfo", "CATALOG"]
