import asyncio
from datetime import UTC, datetime

import pandas as pd
import pytest

from app.service import emissions as oe

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeResponse:
    def __init__(self, records):
        self._records = records

    def to_records(self):
        return self._records


def _fake_client(records, captured_calls):
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_network_data(self, **kwargs):
            captured_calls.append(kwargs)
            return FakeResponse(records)

    return lambda **kwargs: FakeClient()


async def test_fetch_network_data_returns_long_form(monkeypatch):
    # `interval` is naive local-network time in the real SDK response
    # (see `test_fetch_network_data_converts_response_ts_back_to_utc`
    # below) -- a tz-aware fake here doesn't match reality and would
    # break `_fetch_metric`'s `tz_localize` call.
    ts_request = datetime(2026, 1, 1, tzinfo=UTC)
    ts_response_naive_local = datetime(2026, 1, 1, 10, 0)
    records = [
        {"interval": ts_response_naive_local, "fueltech": "coal", "power": 100.0},
        {"interval": ts_response_naive_local, "fueltech": "wind", "power": 50.0},
    ]
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client(records, calls))

    df = await oe.fetch_network_data("NEM", ts_request)

    assert list(df.columns) == ["ts", "fuel_type", "value"]
    assert len(df) == 2
    assert set(df["fuel_type"]) == {"coal", "wind"}
    assert calls[0]["network_code"] == "NEM"
    assert calls[0]["secondary_grouping"] == "fueltech"


async def test_fetch_emissions_returns_long_form(monkeypatch):
    ts_request = datetime(2026, 1, 1, tzinfo=UTC)
    ts_response_naive_local = datetime(2026, 1, 1, 8, 0)  # WEM = AWST
    records = [
        {"interval": ts_response_naive_local, "fueltech": "gas", "emissions": 12.3}
    ]
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client(records, calls))

    df = await oe.fetch_emissions("WEM", ts_request)

    assert list(df.columns) == ["ts", "fuel_type", "value"]
    assert df.iloc[0]["value"] == 12.3


async def test_fetch_network_data_passes_network_region_through(monkeypatch):
    # `todo-model-training.md`'s OE region-join blocker: without this,
    # every NEM query was network-wide only -- no way to ask OE for one
    # region's real numbers.
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client([], calls))

    await oe.fetch_network_data("NEM", ts, network_region="NSW1")

    assert calls[0]["network_region"] == "NSW1"


async def test_fetch_network_data_omits_network_region_when_not_given(monkeypatch):
    # WEM has no sub-regions -- the whole-network query (no
    # `network_region` kwarg passed to the SDK at all) is correct there.
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client([], calls))

    await oe.fetch_network_data("WEM", ts)

    assert calls[0]["network_region"] is None


async def test_fetch_emissions_passes_network_region_through(monkeypatch):
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client([], calls))

    await oe.fetch_emissions("NEM", ts, network_region="QLD1")

    assert calls[0]["network_region"] == "QLD1"


async def test_fetch_network_data_empty_response_returns_empty_frame(monkeypatch):
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client([], []))

    df = await oe.fetch_network_data("NEM", datetime(2026, 1, 1, tzinfo=UTC))

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["ts", "fuel_type", "value"]
    assert df.empty


async def test_missing_api_key_raises_a_catchable_error(monkeypatch):
    # Was a real, unmonkeypatched call relying on OE_API_KEY genuinely
    # being unset in this environment -- broke the moment a real key was
    # added to .env 2026-08-05 to unblock training (this env's own
    # settings are `lru_cache`d process-wide, so it isn't just this
    # test's problem: any code path assuming "no key" would now be
    # silently exercising the real network instead). Monkeypatching
    # `get_settings` to force `oe_api_key=None` makes this test assert
    # the actual thing it's about -- the SDK's own no-key failure mode
    # ingest_openelectricity.run()'s per-network try/except is built to
    # catch -- independent of whatever's actually configured.
    from app.service import emissions as oe_module

    real_settings = oe_module.get_settings()
    no_key_settings = real_settings.model_copy(update={"oe_api_key": None})
    monkeypatch.setattr(oe_module, "get_settings", lambda: no_key_settings)

    with pytest.raises(Exception, match="API key"):
        await oe.fetch_network_data("NEM", datetime(2026, 1, 1, tzinfo=UTC))


async def test_fetch_network_data_sends_naive_local_date_start(monkeypatch):
    # OE's real API rejects a tz-aware `date_start` outright ("Date start
    # must be timezone naive and in network time", confirmed live
    # 2026-08-05) -- this used to pass `since` straight through
    # tz-aware, so every real call (once a key existed to even reach the
    # HTTP request) would have 400'd. NEM is fixed AEST (UTC+10, no DST,
    # confirmed against real API response `date_start`/`date_end`
    # fields), so 00:00 UTC must become naive 10:00 local.
    ts_utc = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client([], calls))

    await oe.fetch_network_data("NEM", ts_utc)

    sent = calls[0]["date_start"]
    assert sent.tzinfo is None
    assert sent == datetime(2026, 1, 1, 10, 0)


async def test_fetch_network_data_uses_wem_awst_offset(monkeypatch):
    ts_utc = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client([], calls))

    await oe.fetch_network_data("WEM", ts_utc)

    sent = calls[0]["date_start"]
    assert sent.tzinfo is None
    assert sent == datetime(2026, 1, 1, 8, 0)


async def test_fetch_network_data_converts_response_ts_back_to_utc(monkeypatch):
    # The SDK's own `to_records()` returns `interval` as a *naive*
    # datetime already shifted into network-local time, not UTC
    # (confirmed by reading `TimeSeriesResponse._create_network_date`
    # directly) -- reusing it as `ts` unconverted would misalign every
    # OE row against AEMO's UTC timestamps by the network's fixed
    # offset once joined. A naive 10:00 (AEST, no tzinfo -- exactly what
    # the real SDK hands back) must become 00:00 UTC.
    naive_local = datetime(2026, 1, 1, 10, 0)  # no tzinfo, like the real SDK
    records = [{"interval": naive_local, "fueltech": "coal", "power": 100.0}]
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client(records, calls))

    df = await oe.fetch_network_data("NEM", datetime(2026, 1, 1, tzinfo=UTC))

    assert df.iloc[0]["ts"] == pd.Timestamp("2026-01-01T00:00:00", tz="UTC")


def _fake_client_hangs_then_succeeds(records, hangs_for_attempts, captured_calls):
    """A fake `AsyncOEClient` whose `get_network_data` never returns for
    the first `hangs_for_attempts` client constructions (simulating the
    real stuck-DNS-resolver-thread hang this module's docstring
    describes), then succeeds on a fresh client after that -- regression
    for the fix itself: `_fetch_metric` must give up on a hung attempt
    (via `asyncio.wait_for`) and retry with a **new** client rather than
    waiting on the same stuck one forever."""
    attempt = {"n": 0}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get_network_data(self, **kwargs):
            captured_calls.append(kwargs)
            attempt["n"] += 1
            if attempt["n"] <= hangs_for_attempts:
                await asyncio.sleep(3600)  # never actually reached -- wait_for cuts in first
            return FakeResponse(records)

    return lambda **kwargs: FakeClient()


async def test_fetch_network_data_retries_past_a_hung_attempt(monkeypatch):
    monkeypatch.setattr(oe, "_REQUEST_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(oe, "_BASE_DELAY_SECONDS", 0.001)
    naive_local = datetime(2026, 1, 1, 10, 0)
    records = [{"interval": naive_local, "fueltech": "coal", "power": 100.0}]
    calls = []
    monkeypatch.setattr(
        oe, "AsyncOEClient", _fake_client_hangs_then_succeeds(records, 1, calls)
    )

    df = await oe.fetch_network_data("NEM", datetime(2026, 1, 1, tzinfo=UTC))

    assert len(df) == 1
    # One hung attempt (timed out, discarded) + one real attempt on a
    # fresh client -- not stuck forever, and not reusing the stuck one.
    assert len(calls) == 2


async def test_fetch_network_data_raises_after_exhausting_retries_on_hang(monkeypatch):
    monkeypatch.setattr(oe, "_REQUEST_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(oe, "_BASE_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(oe, "_MAX_ATTEMPTS", 2)
    calls = []
    monkeypatch.setattr(
        oe, "AsyncOEClient", _fake_client_hangs_then_succeeds([], 99, calls)
    )

    with pytest.raises(TimeoutError):
        await oe.fetch_network_data("NEM", datetime(2026, 1, 1, tzinfo=UTC))

    assert len(calls) == 2
