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
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    records = [
        {"interval": ts, "fueltech": "coal", "power": 100.0},
        {"interval": ts, "fueltech": "wind", "power": 50.0},
    ]
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client(records, calls))

    df = await oe.fetch_network_data("NEM", ts)

    assert list(df.columns) == ["ts", "fuel_type", "value"]
    assert len(df) == 2
    assert set(df["fuel_type"]) == {"coal", "wind"}
    assert calls[0]["network_code"] == "NEM"
    assert calls[0]["secondary_grouping"] == "fueltech"


async def test_fetch_emissions_returns_long_form(monkeypatch):
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    records = [{"interval": ts, "fueltech": "gas", "emissions": 12.3}]
    calls = []
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client(records, calls))

    df = await oe.fetch_emissions("WEM", ts)

    assert list(df.columns) == ["ts", "fuel_type", "value"]
    assert df.iloc[0]["value"] == 12.3


async def test_fetch_network_data_empty_response_returns_empty_frame(monkeypatch):
    monkeypatch.setattr(oe, "AsyncOEClient", _fake_client([], []))

    df = await oe.fetch_network_data("NEM", datetime(2026, 1, 1, tzinfo=UTC))

    assert isinstance(df, pd.DataFrame)
    assert list(df.columns) == ["ts", "fuel_type", "value"]
    assert df.empty


async def test_missing_api_key_raises_a_catchable_error():
    # Real call, no monkeypatching — confirms the actual failure mode
    # ingest_openelectricity.run()'s per-network try/except is built to
    # catch: the SDK itself raises when no API key is configured.
    with pytest.raises(Exception, match="API key"):
        await oe.fetch_network_data("NEM", datetime(2026, 1, 1, tzinfo=UTC))
