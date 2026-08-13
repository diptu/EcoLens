from __future__ import annotations

from app.schemas.base import AppBaseModel
from app.schemas.regions.base import Network


class RegionOut(AppBaseModel):
    id: str
    name: str
    network: Network
