"""`POST /v1/model/train` (Model Operations TODO.md Phase 2) -- manually
publish a training-trigger event, same one `pipeline.flows.
publish_training_trigger` fires automatically after a successful dbt
build. Deliberately open, no auth required -- same reasoning as
`/v1/data-sources/{id}/run`/`/backfill` (see that router's own
docstring): triggering work isn't a privileged action in this
platform's current scope.

`GET /v1/model/training-runs` -- real `meta._training_log` history
(Phase 4), including any currently-`running` row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.deps import get_db
from app.schemas.model import (
    TrainingRunsListResponse,
    TrainRequest,
    TrainTriggerResponse,
)
from app.service.model.actions import list_training_runs, trigger_training

router = APIRouter(prefix="/v1/model", tags=["model"])


@router.post("/train", response_model=TrainTriggerResponse, status_code=202)
async def trigger_training_endpoint(
    body: TrainRequest = TrainRequest(),
) -> TrainTriggerResponse:
    return await trigger_training(
        body.regions, body.window_hours, triggered_by="public"
    )


@router.get("/training-runs", response_model=TrainingRunsListResponse)
async def get_training_runs(
    limit: int = Query(default=20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> TrainingRunsListResponse:
    runs = await list_training_runs(db, limit)
    return TrainingRunsListResponse(data=runs)
