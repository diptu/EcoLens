"""Admin-token gate (`app/core/admin.py`) on write routes the public
dashboard never calls. The dashboard's own triggers (`.../run`,
`.../backfill`) stay open -- see `test_datasource_actions_router.py`."""

from __future__ import annotations

import pytest

from app.core.config import get_settings

from tests.conftest import TEST_ADMIN_TOKEN

GATED = [
    ("patch", "/v1/data-sources/ds-bom", {"enabled": False}),
    ("post", "/v1/ingest/bom", None),
    ("post", "/v1/ingest/aemo_nem/backfill", {"start": "2026-01-01T00:00:00Z", "end": "2026-01-02T00:00:00Z"}),
    ("post", "/v1/features/rebuild", None),
    ("patch", "/v1/anomalies/00000000-0000-0000-0000-000000000000", {"status": "resolved"}),
]


@pytest.mark.parametrize(("method", "path", "body"), GATED)
def test_gated_route_rejects_a_missing_token(anon_client, method, path, body):
    response = anon_client.request(method.upper(), path, json=body)

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize(("method", "path", "body"), GATED)
def test_gated_route_rejects_a_wrong_token(anon_client, method, path, body):
    response = anon_client.request(
        method.upper(), path, json=body, headers={"Authorization": "Bearer nope"}
    )

    assert response.status_code == 401


def test_gated_route_fails_closed_when_no_token_is_configured(anon_client, monkeypatch):
    monkeypatch.delenv("ADMIN_API_TOKEN")
    get_settings.cache_clear()

    response = anon_client.post(
        "/v1/features/rebuild", headers={"X-Admin-Token": TEST_ADMIN_TOKEN}
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "admin_disabled"
