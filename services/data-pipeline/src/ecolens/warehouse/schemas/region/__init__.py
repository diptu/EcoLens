"""`Region` — one row per NEM/WEM region (`dim_region`)."""

from __future__ import annotations

from pydantic import BaseModel


class Region(BaseModel):
    region: str
    state: str
    population: int | None = None
    timezone: str | None = None


__all__ = ["Region"]
