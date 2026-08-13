"""Static catalog backing `GET /v1/data-sources` (API_SPECEFICATIONS.md §1.1).

One entry per `app.service.pipeline.tasks.registry.SOURCES` key — the 5 real
ingest sources this service runs (`task.md`'s "5 fetch-and-store files").
Everything here is deployment config (name, category, URL, license, cron)
that only changes with a code deploy; the bits an admin can actually flip
at runtime (`enabled`) live in Postgres (`meta.data_sources`, see
`app.service.datasources.service`), not here.

Cron strings/timezone are copied from the actual GitHub Actions workflows
that trigger these ingests (`.github/workflows/ingest-*.yml`) — those run
in UTC, so `timezone` is `"UTC"` throughout rather than each source's own
local Australian timezone, to match what the cron string is actually
evaluated against.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.datasources import AuthType, Category
from app.service.pipeline.tasks.registry import SOURCES


@dataclass(frozen=True)
class DataSourceDef:
    id: str
    registry_key: str  # app.service.pipeline.tasks.registry.SOURCES key
    name: str
    category: Category
    description: str
    url: str
    license: str
    auth_type: AuthType
    cron: str
    cadence: str
    timezone: str
    regions: tuple[str, ...]
    metadata: dict[str, object]

    @property
    def ingest_source(self) -> str:
        """The `source` value this catalog entry's runs are logged under in
        `meta._ingest_log` / keyed by in the circuit breaker — i.e.
        `registry.SOURCES[self.registry_key].source`."""
        return SOURCES[self.registry_key].source


_NEM_REGIONS = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")
_ALL_REGIONS = (*_NEM_REGIONS, "WEM")

CATALOG: tuple[DataSourceDef, ...] = (
    DataSourceDef(
        id="ds-oe",
        registry_key="oe",
        name="OpenElectricity",
        category="fuel",
        description=(
            "OpenElectricity (OpenNEM) generation mix by fuel type — NEM "
            "regions (5-min) and WEM (30-min), via the official Python SDK."
        ),
        url="https://explore.openelectricity.org.au/energy/nem/",
        license="CC BY-NC 4.0",
        auth_type="api_key",
        cron="*/5 * * * *",
        cadence="Every 5 minutes",
        timezone="UTC",
        regions=_ALL_REGIONS,
        metadata={
            "registry_key": "oe",
            "ingest_table": "raw.openelectricity_mix",
            "owner_team": "data-eng",
        },
    ),
    DataSourceDef(
        id="ds-aemo-nem",
        registry_key="aemo-nem",
        name="AEMO NEM",
        category="grid",
        description=(
            "Australian Energy Market Operator — NEM (NSW1, QLD1, VIC1, "
            "SA1, TAS1) dispatch demand and price, 5-min resampled to 30-min."
        ),
        url="https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem",
        license="AEMO open data",
        auth_type="none",
        cron="*/15 * * * *",
        cadence="Every 15 minutes",
        timezone="UTC",
        regions=_NEM_REGIONS,
        metadata={
            "registry_key": "aemo-nem",
            "ingest_table": "raw.aemo_nem_dispatch",
            "owner_team": "data-eng",
        },
    ),
    DataSourceDef(
        id="ds-aemo-wem",
        registry_key="aemo-wem",
        name="AEMO WEM",
        category="grid",
        description=(
            "Australian Energy Market Operator — WEM/SWIS half-hourly "
            "demand, generation, and prices."
        ),
        url="https://data.wa.aemo.com.au/",
        license="AEMO open data",
        auth_type="none",
        cron="*/15 * * * *",
        cadence="Every 15 minutes",
        timezone="UTC",
        regions=("WEM",),
        metadata={
            "registry_key": "aemo-wem",
            "ingest_table": "raw.aemo_wem_dispatch",
            "owner_team": "data-eng",
        },
    ),
    DataSourceDef(
        id="ds-bom",
        registry_key="bom",
        name="Bureau of Meteorology",
        category="weather",
        description=(
            "BoM observations (temperature, radiation) — one station per "
            "NEM region plus WEM, 30-min."
        ),
        url="https://www.bom.gov.au/climate/data/",
        license="CC BY 3.0 AU",
        auth_type="api_key",
        cron="*/30 * * * *",
        cadence="Every 30 minutes",
        timezone="UTC",
        regions=_ALL_REGIONS,
        metadata={
            "registry_key": "bom",
            "ingest_table": "raw.bom_observations",
            "owner_team": "data-eng",
        },
    ),
    DataSourceDef(
        id="ds-holidays",
        registry_key="holidays",
        name="AEMO Public Holidays",
        category="custom",
        description=(
            "AEMO calendar — public holidays and workday flags for all 6 "
            "regions, refreshed once a year."
        ),
        url="https://aemo.com.au/energy-systems/electricity/national-electricity-market-nem/data-nem",
        license="AEMO open data",
        auth_type="none",
        cron="0 1 2 1 *",
        cadence="Once a year (Jan 2, 01:00 UTC)",
        timezone="UTC",
        regions=_ALL_REGIONS,
        metadata={
            "registry_key": "holidays",
            "ingest_table": "raw.aemo_holidays",
            "owner_team": "data-eng",
        },
    ),
)

CATALOG_BY_ID: dict[str, DataSourceDef] = {entry.id: entry for entry in CATALOG}
