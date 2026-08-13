"""`GET /v1/data-quality/summary/public` -- ported from data-pipeline's
`app/api/v1/data_quality/routes.py`, the one route this platform's
dashboard actually calls (`services/dashboard`'s `lib/data-quality.ts`'s
own docstring). See `app.service.dataquality`'s module docstring for
what's deliberately not ported (`issues`/`outliers`/`schema`/`recheck`).

No `require_roles` gate -- deliberately, same reasoning data-pipeline's
identical route documents: this exposes only two aggregate numbers (no
source IDs/descriptions), specifically so a browser client (the
dashboard) can call it without holding a bearer token.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db, get_redis_client
from app.schemas.data_quality import PublicDataQualitySummaryResponse
from app.service.dataquality import get_public_summary

router = APIRouter(prefix="/v1/data-quality", tags=["data-quality"])


@router.get("/summary/public", response_model=PublicDataQualitySummaryResponse)
async def get_public_summary_endpoint(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis_client),
) -> PublicDataQualitySummaryResponse:
    return await get_public_summary(db, redis)
