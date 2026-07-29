"""Region-group resolution for `/api/analytics/executive-kpis`.

`fact_demand_30min.region` only ever holds one of the 6 concrete values
in `WarehouseApiSettings.valid_regions` (`NSW1`/`QLD1`/`VIC1`/`SA1`/
`TAS1`/`WEM`) — "NEM" is never itself a stored region value, it's the
AEMO National Electricity Market, the aggregate of the 5 non-WEM
regions. The existing `warehouse.repository.queries.get_national_*`
helpers sum *every* row in `fact_demand_30min` unconditionally, which
in practice means NEM+WEM combined, not NEM alone — fine for those
endpoints' own "national" framing, but wrong for this endpoint's
`region=NEM` default (the KPI spec's own region enum lists `NEM` and
`WEM` as siblings, so `NEM` must exclude WEM here). Hence this
module's own region-list resolution instead of reusing those helpers.
"""

from __future__ import annotations

NEM_SUB_REGIONS: tuple[str, ...] = ("NSW1", "QLD1", "VIC1", "SA1", "TAS1")

# Superset of `WarehouseApiSettings.valid_regions` (adds "NEM") -- this
# endpoint's own region enum per the spec, kept local rather than
# widening that shared setting, which every *other* warehouse route
# (scoped to one concrete region, never a pseudo-aggregate) still needs
# to reject "NEM" for.
ANALYTICS_VALID_REGIONS: tuple[str, ...] = ("NEM", *NEM_SUB_REGIONS, "WEM")


def resolve_region_group(region: str) -> tuple[str, ...]:
    """The concrete `fact_demand_30min.region` values to filter on for
    `region`. Raises `ValueError` for anything outside
    `ANALYTICS_VALID_REGIONS` -- callers validate before this (see
    `api/read_dependencies.py`), so this is a defensive check, not the
    primary 400 path.
    """
    if region not in ANALYTICS_VALID_REGIONS:
        raise ValueError(f"unknown region {region!r}; valid: {ANALYTICS_VALID_REGIONS}")
    if region == "NEM":
        return NEM_SUB_REGIONS
    return (region,)


__all__ = ["NEM_SUB_REGIONS", "ANALYTICS_VALID_REGIONS", "resolve_region_group"]
