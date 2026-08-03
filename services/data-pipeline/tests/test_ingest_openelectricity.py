from contextlib import asynccontextmanager

import pytest

from app.service.pipeline.tasks import _common, ingest_openelectricity

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _PassthroughBreaker:
    async def call(self, fn, *args, **kwargs):
        return await fn(*args, **kwargs)

    @property
    def state(self):
        return self._compute_state()

    async def _compute_state(self):
        from app.service.pipeline.circuit_breaker import CircuitState

        return CircuitState.CLOSED


class _FakeSession:
    async def execute(self, *args, **kwargs):
        return None


@asynccontextmanager
async def _fake_get_session():
    yield _FakeSession()


def _fake_stage_dataframe(df, table, run_id):
    # Real stage_dataframe writes an actual DuckDB file -- unnecessary
    # I/O for these unit tests, and irrelevant to what they're actually
    # verifying (the emissions-merge/intensity math and the run()
    # control flow), so it's faked out same as get_session/get_breaker
    # below.
    if df.empty:
        return "", 0
    return f"/fake/staging/{table}", len(df)


async def _fake_publish_landed_event(payload):
    pass


def _fake_detect_anomalies(df, source):
    return df.iloc[0:0]


async def _fake_record_anomalies(run_id, source, table, anomalies):
    pass


@pytest.fixture(autouse=True)
def _bypass_real_db_and_breaker(monkeypatch):
    monkeypatch.setattr(_common, "get_breaker", lambda name: _PassthroughBreaker())
    monkeypatch.setattr(_common, "get_session", _fake_get_session)
    monkeypatch.setattr(_common, "stage_dataframe", _fake_stage_dataframe)
    monkeypatch.setattr(_common, "publish_landed_event", _fake_publish_landed_event)
    monkeypatch.setattr(_common, "detect_anomalies", _fake_detect_anomalies)
    monkeypatch.setattr(_common, "record_anomalies", _fake_record_anomalies)


async def test_run_degrades_to_zero_rows_without_a_live_oe_api_key():
    # No OE_API_KEY configured -> fetch_network_data raises for every
    # region; ingest_openelectricity.run() catches that per-region and
    # returns an empty DataFrame, which land_and_load then no-ops on
    # (verified separately in test_landing.py) rather than crashing the
    # whole run. This is the real, currently-true fallback in this
    # environment -- nothing here is mocked beyond DB/breaker.
    rows_loaded = await ingest_openelectricity.run(lookback_minutes=30)

    assert rows_loaded == 0


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

    async def _fake_fetch_emissions(network, since):
        assert network == "NEM"
        return long_df

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    from datetime import UTC, datetime

    out = await ingest_openelectricity._fetch_total_emissions("NEM", datetime.now(UTC))

    assert list(out.columns) == ["ts", "total_emissions_kg"]
    assert out.loc[0, "total_emissions_kg"] == pytest.approx(15.0)


async def test_fetch_total_emissions_empty_response_returns_empty_shaped_frame(
    monkeypatch,
):
    import pandas as pd

    async def _fake_fetch_emissions(network, since):
        return pd.DataFrame(columns=["ts", "fuel_type", "value"])

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    from datetime import UTC, datetime

    out = await ingest_openelectricity._fetch_total_emissions("NEM", datetime.now(UTC))

    assert list(out.columns) == ["ts", "total_emissions_kg"]
    assert out.empty


async def test_run_merges_emissions_into_intensity_end_to_end(monkeypatch):
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01T00:00", tz="UTC")

    async def _fake_fetch_network_data(network, since):
        if network != "NEM":
            return pd.DataFrame(columns=["ts", "fuel_type", "value"])
        return pd.DataFrame({"ts": [ts0], "fuel_type": ["coal"], "value": [100.0]})

    async def _fake_fetch_emissions(network, since):
        if network != "NEM":
            return pd.DataFrame(columns=["ts", "fuel_type", "value"])
        return pd.DataFrame({"ts": [ts0], "fuel_type": ["coal"], "value": [10.0]})

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_network_data", _fake_fetch_network_data
    )
    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    rows_loaded = await ingest_openelectricity.run(lookback_minutes=30)

    # 5 NEM regions each land one row (fallback interval = 5min ->
    # generation_mwh = 100 * 5/60, intensity = 10 / that > 0), WEM lands
    # nothing since fetch_network_data returns empty for it here.
    assert rows_loaded == 5


async def test_run_keeps_generation_row_when_emissions_fetch_fails(monkeypatch):
    import pandas as pd

    ts0 = pd.Timestamp("2026-01-01T00:00", tz="UTC")

    async def _fake_fetch_network_data(network, since):
        if network != "NEM":
            return pd.DataFrame(columns=["ts", "fuel_type", "value"])
        return pd.DataFrame({"ts": [ts0], "fuel_type": ["coal"], "value": [100.0]})

    async def _fake_fetch_emissions(network, since):
        raise RuntimeError("emissions endpoint down")

    monkeypatch.setattr(
        ingest_openelectricity, "fetch_network_data", _fake_fetch_network_data
    )
    monkeypatch.setattr(
        ingest_openelectricity, "fetch_emissions", _fake_fetch_emissions
    )

    rows_loaded = await ingest_openelectricity.run(lookback_minutes=30)

    assert rows_loaded == 5
