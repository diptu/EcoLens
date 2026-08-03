from __future__ import annotations

import json

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.config import get_settings


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, row):
        self.row = row

    async def execute(self, query, params=None):
        return _FakeResult(self.row)


def test_missing_region_closes_with_policy_violation(client):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/v1/stream/emissions"):
            pass

    assert exc_info.value.code == 4400


def test_streams_the_latest_intensity_row(client, monkeypatch):
    from datetime import UTC, datetime

    row = {
        "hour": datetime(2026, 1, 1, 10, tzinfo=UTC),
        "region": "NSW1",
        "total_generation_mwh": 1000.0,
        "total_emissions_kgco2e": 446000.0,
        "intensity_kgco2e_per_mwh": 446.0,
        "factors_version": "nger-2025-q4",
    }

    import contextlib

    @contextlib.asynccontextmanager
    async def fake_get_session():
        yield _FakeSession(row)

    monkeypatch.setattr("app.api.v1.stream.routes.get_session", fake_get_session)
    # Short interval so the test doesn't wait the real 5-minute default.
    get_settings.cache_clear()
    monkeypatch.setenv("STREAM_INTERVAL_SECONDS", "0.01")

    with client.websocket_connect("/v1/stream/emissions?region=NSW1") as ws:
        message = ws.receive_text()
        payload = json.loads(message)

    assert payload["region"] == "NSW1"
    assert payload["intensity_kgco2e_per_mwh"] == 446.0
    get_settings.cache_clear()
