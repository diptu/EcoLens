"""Tests for ecolens.warehouse.service.executive_kpis.

Unlike `conftest.FakeConnectionPool` (one canned result reused for
every call), `build_executive_kpis` needs *different* results for its
current-period vs. previous-period `fetchrow` calls to exercise
`delta_pct`/`trend` meaningfully -- `_SequencedPool` below queues one
result per call, consumed in call order.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from ecolens.warehouse.service.executive_kpis import build_executive_kpis

NOW = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)


class _SequencedPool:
    def __init__(
        self,
        fetchrow_results: list[dict[str, Any]],
        fetch_result: list[dict[str, Any]] | None = None,
    ) -> None:
        self.is_connected = True
        self._fetchrow_results = list(fetchrow_results)
        self._fetch_result = fetch_result or []
        self.fetchrow_calls: list[tuple[Any, ...]] = []
        self.fetch_calls: list[tuple[Any, ...]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any]:
        self.fetchrow_calls.append(args)
        return self._fetchrow_results.pop(0)

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append(args)
        return self._fetch_result


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[tuple[str, Any]] = []

    async def get(self, key: str) -> Any | None:
        self.get_calls.append(key)
        return self.store.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.set_calls.append((key, value))
        self.store[key] = value


_CURRENT = {
    "total_carbon_tco2e": 12_840.0,
    "avg_emissions_intensity_kgco2e_per_mwh": 612.0,
    "avg_renewable_proportion": 38.6,
    "total_energy_mwh": 1_000_000.0,
}
_PREVIOUS = {
    "total_carbon_tco2e": 13_403.0,
    "avg_emissions_intensity_kgco2e_per_mwh": 630.0,
    "avg_renewable_proportion": 36.4,
    "total_energy_mwh": 950_000.0,
}


class TestBuildExecutiveKpis:
    @pytest.mark.asyncio
    async def test_returns_six_kpi_cards_in_the_documented_order(self):
        pool = _SequencedPool([_CURRENT, _PREVIOUS])
        payload, cache_hit = await build_executive_kpis(
            pool, None, period="ytd", region="NEM", currency="AUD", now=NOW
        )
        assert cache_hit is False
        ids = [k["id"] for k in payload["kpis"]]
        assert ids == [
            "total-co2e",
            "carbon-intensity",
            "renewable-share",
            "cost-savings",
            "compliance-score",
            "open-risks",
        ]

    @pytest.mark.asyncio
    async def test_total_co2e_reflects_real_query_data(self):
        pool = _SequencedPool([_CURRENT, _PREVIOUS])
        payload, _ = await build_executive_kpis(
            pool, None, period="ytd", region="NEM", currency="AUD", now=NOW
        )
        co2e = next(k for k in payload["kpis"] if k["id"] == "total-co2e")
        assert co2e["value"] == 12_840.0
        assert co2e["trend"] == "down"  # 12840 < 13403
        assert co2e["good_when"] == "down"
        assert co2e["is_good"] is True
        assert co2e["delta_pct"] < 0

    @pytest.mark.asyncio
    async def test_renewable_share_up_is_good(self):
        pool = _SequencedPool([_CURRENT, _PREVIOUS])
        payload, _ = await build_executive_kpis(
            pool, None, period="ytd", region="NEM", currency="AUD", now=NOW
        )
        share = next(k for k in payload["kpis"] if k["id"] == "renewable-share")
        assert share["value"] == 38.6
        assert share["trend"] == "up"  # 38.6 > 36.4
        assert share["is_good"] is True

    @pytest.mark.asyncio
    async def test_unavailable_kpis_are_null_valued_and_neutral(self):
        pool = _SequencedPool([_CURRENT, _PREVIOUS])
        payload, _ = await build_executive_kpis(
            pool, None, period="ytd", region="NEM", currency="AUD", now=NOW
        )
        for kpi_id in ("cost-savings", "compliance-score", "open-risks"):
            kpi = next(k for k in payload["kpis"] if k["id"] == kpi_id)
            assert kpi["value"] is None
            assert kpi["value_display"] == "—"
            assert kpi["trend"] == "flat"
            assert kpi["is_good"] is True  # neutral, not a false red flag
            assert kpi["sub"]  # explains why it's unavailable

    @pytest.mark.asyncio
    async def test_no_previous_period_data_gives_null_delta_not_a_crash(self):
        pool = _SequencedPool([_CURRENT, {}])  # previous: empty dict (no rows)
        payload, _ = await build_executive_kpis(
            pool, None, period="ytd", region="NEM", currency="AUD", now=NOW
        )
        co2e = next(k for k in payload["kpis"] if k["id"] == "total-co2e")
        assert co2e["delta_pct"] is None
        assert co2e["trend"] == "flat"

    @pytest.mark.asyncio
    async def test_meta_echoes_request_params_and_windows(self):
        pool = _SequencedPool([_CURRENT, _PREVIOUS])
        payload, _ = await build_executive_kpis(
            pool, None, period="qtd", region="WEM", currency="USD", now=NOW
        )
        meta = payload["meta"]
        assert meta["period"] == "qtd"
        assert meta["region"] == "WEM"
        assert meta["currency"] == "USD"
        assert meta["previous_period"]["start"] < meta["previous_period"]["end"]

    @pytest.mark.asyncio
    async def test_region_group_is_resolved_before_querying(self):
        pool = _SequencedPool([_CURRENT, _PREVIOUS])
        await build_executive_kpis(
            pool, None, period="ytd", region="NEM", currency="AUD", now=NOW
        )
        first_call_regions = pool.fetchrow_calls[0][0]
        assert set(first_call_regions) == {"NSW1", "QLD1", "VIC1", "SA1", "TAS1"}

    @pytest.mark.asyncio
    async def test_cache_hit_skips_the_pool_entirely(self):
        cache = _FakeCache()
        cache.store["exec:kpis:v1:ytd:NEM:AUD"] = {"meta": {}, "kpis": []}
        pool = _SequencedPool([])  # would raise IndexError if ever called
        payload, cache_hit = await build_executive_kpis(
            pool, cache, period="ytd", region="NEM", currency="AUD", now=NOW
        )
        assert cache_hit is True
        assert payload == {"meta": {}, "kpis": []}
        assert pool.fetchrow_calls == []

    @pytest.mark.asyncio
    async def test_cache_miss_populates_the_cache(self):
        cache = _FakeCache()
        pool = _SequencedPool([_CURRENT, _PREVIOUS])
        _, cache_hit = await build_executive_kpis(
            pool, cache, period="ytd", region="NEM", currency="AUD", now=NOW
        )
        assert cache_hit is False
        assert "exec:kpis:v1:ytd:NEM:AUD" in cache.store
