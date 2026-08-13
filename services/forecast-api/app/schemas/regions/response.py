from __future__ import annotations

from app.schemas.base import AppBaseModel
from app.schemas.regions.entities import RegionOut


class RegionsResponse(AppBaseModel):
    data: list[RegionOut]
