import pytest

from app.service.pipeline.tasks import ingest_openelectricity

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


# Note: data-pipeline's identical test file also has an autouse
# `_bypass_real_db_and_breaker` fixture patching `_common.get_breaker`/
# `get_session`/`stage_dataframe`/`publish_landed_event`/
# `detect_anomalies`/`record_anomalies` -- dead weight here and dropped:
# `ingest_openelectricity.py` never touches any of those (no `@timed`,
# no breaker call, no staging/publish/anomaly) -- confirmed directly
# from its own source, not assumed -- and this service's own minimal
# `_common.py` (services/ingestion/TODO.md Phase 1) doesn't even define
# those attributes yet, so patching them here would raise `AttributeError`
# rather than silently no-op.


async def test_run_degrades_to_zero_rows_without_a_live_oe_api_key(monkeypatch):
    # Was a real, unmonkeypatched call relying on OE_API_KEY genuinely
    # being unset in this environment -- broke the moment a real key was
    # added to .env 2026-08-05 to unblock training. Monkeypatching
    # `emissions.get_settings` (where the actual no-key check happens,
    # inside `_fetch_metric`) to force `oe_api_key=None` makes this test
    # assert the real, still-true fallback -- fetch_network_data raises
    # for every region, run() catches it per-region and returns an empty
    # DataFrame -- independent of whatever's actually configured.
    from app.service import emissions as oe_module

    real_settings = oe_module.get_settings()
    no_key_settings = real_settings.model_copy(update={"oe_api_key": None})
    monkeypatch.setattr(oe_module, "get_settings", lambda: no_key_settings)

    result_df = await ingest_openelectricity.run(lookback_minutes=30)

    assert result_df.empty


def test_pivot_long_to_wide_sums_colliding_fueltechs_into_one_column():
    """Regression: the real OE API sends `"battery"` AND
    `"battery_discharging"` simultaneously (confirmed live 2026-08-05) --
    both map to `battery_discharge_mw`. The naive rename this used to do
    only renamed the first one and silently left the second one
    un-renamed under its *original* fuel_type name -- which isn't just a
    dropped-generation bug, it broke the actual Postgres load outright
    (`column "battery_discharging" ... does not exist`, confirmed live:
    `raw.openelectricity_mix` has no such column). Fixed version must
    sum both into the one real destination column, and the orphaned
    original-named column must not appear in the output at all."""
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01", tz="UTC")
    long_df = pd.DataFrame(
        {
            "ts": [ts0, ts0],
            "fuel_type": ["battery", "battery_discharging"],
            "value": [10.0, 25.0],
        }
    )

    wide = ingest_openelectricity._pivot_long_to_wide(long_df, "NEM", "NSW1")

    assert wide.loc[0, "battery_discharge_mw"] == pytest.approx(35.0)
    assert "battery_discharging" not in wide.columns
    assert "battery" not in wide.columns


def test_pivot_long_to_wide_matches_the_raw_openelectricity_mix_schema():
    import pandas as pd

    long_df = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2026-01-01", tz="UTC")] * 2,
            "fuel_type": ["coal", "wind"],
            "value": [100.0, 50.0],
        }
    )

    wide = ingest_openelectricity._pivot_long_to_wide(long_df, "NEM", "NSW1")

    expected = {
        "ts",
        "network_code",
        "region",
        "coal_mw",
        "gas_mw",
        "hydro_mw",
        "wind_mw",
        "solar_utility_mw",
        "solar_rooftop_mw",
        "battery_discharge_mw",
        "battery_charge_mw",
        "pumped_hydro_mw",
        "biomass_mw",
        "distillate_mw",
        "total_generation_mw",
        "total_renewable_mw",
        "demand_mw",
        "price_mwh",
        "intensity_kg_per_mwh",
    }
    assert expected.issubset(set(wide.columns))
    assert wide.loc[0, "coal_mw"] == 100.0
    assert wide.loc[0, "wind_mw"] == 50.0


def test_pivot_long_to_wide_maps_the_real_oe_fueltech_taxonomy():
    """Regression: the real OE API returns `coal_black`/`coal_brown`/
    `gas_ccgt`/`gas_ocgt`/`bioenergy_biomass`/`pumps` (confirmed live
    2026-08-05, `openelectricity.types.UnitFueltechType`'s own canonical
    enum) -- the old `_FUEL_COLUMN_MAP` only recognized
    `"coal"`/`"black_coal"`/`"ccgt"`/`"biomass"`/`"pumped_hydro"`, none
    of which the real API ever actually sends, so every real
    coal/CCGT/OCGT/biomass/pumped-hydro row was silently dropped from
    `total_generation_mw` -- the single largest share of real
    generation, in production this would have made the feature that
    unblocked training subtly, catastrophically wrong (near-zero instead
    of ~5-7 GW) rather than genuinely fixed."""
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01", tz="UTC")
    long_df = pd.DataFrame(
        {
            "ts": [ts0] * 4,
            "fuel_type": ["coal_black", "gas_ccgt", "bioenergy_biomass", "pumps"],
            "value": [5000.0, 200.0, 40.0, 10.0],
        }
    )

    wide = ingest_openelectricity._pivot_long_to_wide(long_df, "NEM", "NSW1")

    assert wide.loc[0, "coal_mw"] == 5000.0
    assert wide.loc[0, "gas_mw"] == 200.0
    assert wide.loc[0, "biomass_mw"] == 40.0
    assert wide.loc[0, "pumped_hydro_mw"] == 10.0
    assert wide.loc[0, "total_generation_mw"] == pytest.approx(5250.0)


def test_pivot_long_to_wide_without_emissions_leaves_intensity_none():
    import pandas as pd

    long_df = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2026-01-01", tz="UTC")] * 2,
            "fuel_type": ["coal", "wind"],
            "value": [100.0, 50.0],
        }
    )

    wide = ingest_openelectricity._pivot_long_to_wide(long_df, "NEM", "NSW1")

    assert wide.loc[0, "intensity_kg_per_mwh"] is None


def test_pivot_long_to_wide_computes_intensity_from_emissions():
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01T00:00", tz="UTC")
    ts1 = pd.Timestamp("2026-01-01T00:05", tz="UTC")
    long_df = pd.DataFrame(
        {
            "ts": [ts0, ts0, ts1, ts1],
            "fuel_type": ["coal", "wind", "coal", "wind"],
            "value": [100.0, 50.0, 100.0, 50.0],
        }
    )
    # 150 MW total generation, 5-minute interval -> 12.5 MWh
    # 25 kg emitted in that interval -> 2.0 kg/MWh
    emissions_by_ts = pd.DataFrame(
        {"ts": [ts0, ts1], "total_emissions_kg": [25.0, 25.0]}
    )

    wide = ingest_openelectricity._pivot_long_to_wide(
        long_df, "NEM", "NSW1", emissions_by_ts
    )

    assert wide.loc[0, "intensity_kg_per_mwh"] == pytest.approx(2.0)
    assert wide.loc[1, "intensity_kg_per_mwh"] == pytest.approx(2.0)


def test_pivot_long_to_wide_guards_division_by_zero_generation():
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01T00:00", tz="UTC")
    long_df = pd.DataFrame({"ts": [ts0], "fuel_type": ["coal"], "value": [0.0]})
    emissions_by_ts = pd.DataFrame({"ts": [ts0], "total_emissions_kg": [5.0]})

    wide = ingest_openelectricity._pivot_long_to_wide(
        long_df, "NEM", "NSW1", emissions_by_ts
    )

    assert pd.isna(wide.loc[0, "intensity_kg_per_mwh"])


def test_infer_interval_hours_from_median_spacing():
    import pandas as pd

    ts = pd.Series(
        [
            pd.Timestamp("2026-01-01T00:00", tz="UTC"),
            pd.Timestamp("2026-01-01T00:05", tz="UTC"),
            pd.Timestamp("2026-01-01T00:10", tz="UTC"),
        ]
    )

    assert ingest_openelectricity._infer_interval_hours(ts) == pytest.approx(5 / 60)


def test_infer_interval_hours_falls_back_with_one_timestamp():
    import pandas as pd

    ts = pd.Series([pd.Timestamp("2026-01-01T00:00", tz="UTC")])

    assert ingest_openelectricity._infer_interval_hours(ts) == pytest.approx(
        ingest_openelectricity._FALLBACK_INTERVAL_HOURS
    )


async def test_fetch_total_emissions_sums_by_timestamp(monkeypatch):
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01T00:00", tz="UTC")
    long_df = pd.DataFrame(
        {"ts": [ts0, ts0], "fuel_type": ["coal", "gas"], "value": [10.0, 5.0]}
    )

    async def _fake_fetch_emissions(network, since, network_region=None, until=None):
        assert network == "NEM"
        return long_df

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    from datetime import UTC, datetime

    out = await ingest_openelectricity._fetch_total_emissions("NEM", datetime.now(UTC))

    assert list(out.columns) == ["ts", "total_emissions_kg"]
    assert out.loc[0, "total_emissions_kg"] == pytest.approx(15.0)


async def test_fetch_total_emissions_passes_network_region_through(monkeypatch):
    import pandas as pd

    captured = {}

    async def _fake_fetch_emissions(network, since, network_region=None, until=None):
        captured["network_region"] = network_region
        return pd.DataFrame(columns=["ts", "fuel_type", "value"])

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    from datetime import UTC, datetime

    await ingest_openelectricity._fetch_total_emissions(
        "NEM", datetime.now(UTC), network_region="NSW1"
    )

    assert captured["network_region"] == "NSW1"


async def test_fetch_total_emissions_empty_response_returns_empty_shaped_frame(
    monkeypatch,
):
    import pandas as pd

    async def _fake_fetch_emissions(network, since, network_region=None, until=None):
        return pd.DataFrame(columns=["ts", "fuel_type", "value"])

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    from datetime import UTC, datetime

    out = await ingest_openelectricity._fetch_total_emissions("NEM", datetime.now(UTC))

    assert list(out.columns) == ["ts", "total_emissions_kg"]
    assert out.empty


async def test_run_queries_each_nem_region_separately_not_the_whole_network(
    monkeypatch,
):
    """Regression for `todo-model-training.md`'s OE region-join blocker:
    `run()` used to call `fetch_network_data(net, since=since)` -- no
    region scoping at all -- once per NEM region, getting back the exact
    same network-wide answer each time and just relabeling it. Fixed
    version must pass a *different* `network_region` for each of the 5
    NEM regions, and `None` for WEM (no sub-regions of its own)."""
    import pandas as pd

    captured_regions: list[tuple[str, str | None]] = []

    async def _fake_fetch_network_data(network, since, network_region=None, until=None):
        captured_regions.append((network, network_region))
        return pd.DataFrame(columns=["ts", "fuel_type", "value"])

    async def _fake_fetch_emissions(network, since, network_region=None, until=None):
        return pd.DataFrame(columns=["ts", "fuel_type", "value"])

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_network_data", _fake_fetch_network_data
    )
    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    await ingest_openelectricity.run(lookback_minutes=30)

    assert captured_regions == [
        ("NEM", "NSW1"),
        ("NEM", "QLD1"),
        ("NEM", "VIC1"),
        ("NEM", "SA1"),
        ("NEM", "TAS1"),
        ("WEM", None),
    ]
    # Every NEM call got its own distinct region -- not 5 identical calls.
    nem_regions = [r for net, r in captured_regions if net == "NEM"]
    assert len(set(nem_regions)) == 5


async def test_run_merges_emissions_into_intensity_end_to_end(monkeypatch):
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01T00:00", tz="UTC")

    async def _fake_fetch_network_data(network, since, network_region=None, until=None):
        if network != "NEM":
            return pd.DataFrame(columns=["ts", "fuel_type", "value"])
        return pd.DataFrame({"ts": [ts0], "fuel_type": ["coal"], "value": [100.0]})

    async def _fake_fetch_emissions(network, since, network_region=None, until=None):
        if network != "NEM":
            return pd.DataFrame(columns=["ts", "fuel_type", "value"])
        return pd.DataFrame({"ts": [ts0], "fuel_type": ["coal"], "value": [10.0]})

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_network_data", _fake_fetch_network_data
    )
    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    result_df = await ingest_openelectricity.run(lookback_minutes=30)

    # 5 NEM regions each land one row (fallback interval = 5min ->
    # generation_mwh = 100 * 5/60, intensity = 10 / that > 0), WEM lands
    # nothing since fetch_network_data returns empty for it here. The
    # fake ignores `network_region` and returns the same shape for any
    # NEM call, same as before the fix -- this test is about the
    # emissions-merge/intensity math, not the per-region query itself
    # (see test_run_queries_each_nem_region_separately_not_the_whole_network
    # for that).
    assert len(result_df) == 5


async def test_run_keeps_generation_row_when_emissions_fetch_fails(monkeypatch):
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01T00:00", tz="UTC")

    async def _fake_fetch_network_data(network, since, network_region=None, until=None):
        if network != "NEM":
            return pd.DataFrame(columns=["ts", "fuel_type", "value"])
        return pd.DataFrame({"ts": [ts0], "fuel_type": ["coal"], "value": [100.0]})

    async def _fake_fetch_emissions(network, since, network_region=None, until=None):
        raise RuntimeError("emissions endpoint down")

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_network_data", _fake_fetch_network_data
    )
    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    result_df = await ingest_openelectricity.run(lookback_minutes=30)

    assert len(result_df) == 5


async def test_run_with_start_and_end_routes_to_the_historical_fetch(monkeypatch):
    import pandas as pd

    called_with = {}

    async def fake_historical_range(start, end):
        called_with["start"] = start
        called_with["end"] = end
        return pd.DataFrame([{"ts": start, "region": "NSW1", "network_code": "NEM"}])

    monkeypatch.setattr(
        ingest_openelectricity, "_fetch_historical_range", fake_historical_range
    )

    from datetime import UTC, datetime

    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 7, 2, tzinfo=UTC)
    # `run()` is deliberately *not* `@standard_run`-decorated (its own
    # docstring, 2026-08-05) -- it returns the raw DataFrame
    # `_fetch_historical_range` produces, with `run_source` applying
    # `standard_run`'s staging/logging/row-count-return contract
    # dynamically at call time instead (`registry.SOURCES["oe"].
    # self_wrapped = False`).
    result_df = await ingest_openelectricity.run(start=start, end=end)

    assert called_with == {"start": start, "end": end}
    assert len(result_df) == 1


async def test_fetch_historical_range_covers_each_calendar_day_inclusive(monkeypatch):
    """`[start.date(), end.date()]` inclusive -- matching
    `ingest_aemo_nem.py`/`ingest_bom.py`'s own historical-range
    convention, since `pipeline.backfill`'s `backfill_day` relies on it
    (passes `start == end` for exactly one day)."""
    import pandas as pd

    captured_days = []

    async def fake_fetch_all_regions(since, until=None):
        captured_days.append((since, until))
        return pd.DataFrame([{"ts": since, "region": "NSW1", "network_code": "NEM"}])

    monkeypatch.setattr(
        ingest_openelectricity, "_fetch_all_regions", fake_fetch_all_regions
    )

    from datetime import UTC, datetime

    start = datetime(2026, 7, 1, tzinfo=UTC)
    end = datetime(2026, 7, 3, tzinfo=UTC)
    df = await ingest_openelectricity._fetch_historical_range(start, end)

    assert captured_days == [
        (datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 2, tzinfo=UTC)),
        (datetime(2026, 7, 2, tzinfo=UTC), datetime(2026, 7, 3, tzinfo=UTC)),
        (datetime(2026, 7, 3, tzinfo=UTC), datetime(2026, 7, 4, tzinfo=UTC)),
    ]
    assert len(df) == 3


async def test_fetch_historical_range_skips_a_day_with_no_data(monkeypatch):
    import pandas as pd

    async def fake_fetch_all_regions(since, until=None):
        # Every day returns empty -- e.g. a real range before any real
        # data existed.
        return pd.DataFrame()

    monkeypatch.setattr(
        ingest_openelectricity, "_fetch_all_regions", fake_fetch_all_regions
    )

    from datetime import UTC, datetime

    df = await ingest_openelectricity._fetch_historical_range(
        datetime(2026, 7, 1, tzinfo=UTC), datetime(2026, 7, 1, tzinfo=UTC)
    )

    assert df.empty


async def test_fetch_all_regions_passes_until_through_to_every_call(monkeypatch):
    """Regression: `_fetch_all_regions` (shared by `run()`'s
    `lookback_minutes` path and `_fetch_historical_range`'s per-day
    backfill) must forward `until` to both `fetch_network_data` and
    `_fetch_total_emissions` for every region -- a day-chunked backfill
    that silently dropped `until` would fetch "since day_start through
    now" every time instead of just that one day."""
    import pandas as pd

    ts0 = pd.Timestamp("2026-07-01", tz="UTC")
    captured = []

    async def fake_fetch_network_data(network, since, network_region=None, until=None):
        captured.append((network, network_region, "power", until))
        # Non-empty -- `_fetch_all_regions` only fetches emissions for a
        # region after a non-empty generation result (`if long_df.empty:
        # continue`), same real-world behavior this is regression-
        # testing `until`'s propagation through.
        return pd.DataFrame({"ts": [ts0], "fuel_type": ["coal"], "value": [100.0]})

    async def fake_fetch_emissions(network, since, network_region=None, until=None):
        captured.append((network, network_region, "emissions", until))
        return pd.DataFrame(columns=["ts", "fuel_type", "value"])

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_network_data", fake_fetch_network_data
    )
    monkeypatch.setattr(ingest_openelectricity, "fetch_emissions", fake_fetch_emissions)

    from datetime import UTC, datetime

    since = datetime(2026, 7, 1, tzinfo=UTC)
    until = datetime(2026, 7, 2, tzinfo=UTC)
    await ingest_openelectricity._fetch_all_regions(since, until=until)

    assert len(captured) == 12  # 6 regions x 2 metrics
    assert all(u == until for *_rest, u in captured)
