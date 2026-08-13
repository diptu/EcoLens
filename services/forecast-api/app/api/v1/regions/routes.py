"""`GET /v1/regions` (`README.md` § API reference).

Static — the 6 regions this platform's ingestion actually covers
(`data-pipeline`'s `datasources.catalog`'s NEM regions + WEM), not a DB
query. No new region has ever been added without a code change on the
ingestion side either, so a static list here isn't a staleness risk
beyond what's already true of the rest of the platform.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.regions import RegionOut, RegionsResponse

router = APIRouter(prefix="/v1", tags=["regions"])

_REGIONS: tuple[RegionOut, ...] = (
    RegionOut(id="NSW1", name="New South Wales", network="NEM"),
    RegionOut(id="QLD1", name="Queensland", network="NEM"),
    RegionOut(id="VIC1", name="Victoria", network="NEM"),
    RegionOut(id="SA1", name="South Australia", network="NEM"),
    RegionOut(id="TAS1", name="Tasmania", network="NEM"),
    RegionOut(id="WEM", name="Western Australia (SWIS)", network="WEM"),
)


@router.get("/regions", response_model=RegionsResponse)
async def list_regions() -> RegionsResponse:
    return RegionsResponse(data=list(_REGIONS))
