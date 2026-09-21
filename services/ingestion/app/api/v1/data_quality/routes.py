"""`GET /v1/data-quality/summary/public` -- ported from data-pipeline's
`app/api/v1/data_quality/routes.py`, the one route this platform's
dashboard actually calls (`services/dashboard`'s `lib/data-quality.ts`'s
own docstring). See `app.service.dataquality`'s module docstring for
what's deliberately not ported (`issues`/`outliers`/`schema`/`recheck`).

No `require_roles` gate -- deliberately, same reasoning data-pipeline's
identical route documents: this exposes only two aggregate numbers (no
source IDs/descriptions), specifically so a browser client (the
dashboard) can call it without holding a bearer token.

`GET /v1/data-quality/open-risks` (2026-08-20) -- the real per-issue
detail behind the summary's `open_risks_high_plus` count, added because
the Executive Dashboard's "Open Risks" KPI had no way to show which
service was affected or why, only a bare number. Same no-auth reasoning
as the summary route above -- this platform has no auth anywhere yet
(`app/api/v1/model/routes.py`'s forecast-api counterpart states the same
"triggering/reading work isn't a privileged action" position), and
unlike the old data-pipeline `issues` route this doesn't expose anything
more sensitive than a source name + a human-readable description.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db, get_redis_client
from app.schemas.data_quality import OpenRisksListResponse, PublicDataQualitySummaryResponse
from app.service.dataquality import get_open_risks, get_public_summary

router = APIRouter(prefix="/v1/data-quality", tags=["data-quality"])


@router.get("/summary/public", response_model=PublicDataQualitySummaryResponse)
async def get_public_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> PublicDataQualitySummaryResponse:
    return await get_public_summary(db, redis)


@router.get("/open-risks", response_model=OpenRisksListResponse)
async def get_open_risks_endpoint(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> OpenRisksListResponse:
    return await get_open_risks(db, redis)
