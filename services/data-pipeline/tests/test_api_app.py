"""Tests for ecolens.api.app -- the data-pipeline control API's app
factory (`make pipeline` serves this). Just confirms both control
routers (forecasting, ingestion) are actually mounted; each router's
own behavior is covered by test_forecasting_api.py/test_ingestion_api.py.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ecolens.api.app import app, create_app


def test_mounts_forecasting_and_ingestion_routers():
    with TestClient(app) as client:
        schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/forecasting/train" in paths
    assert "/forecasting/status" in paths
    assert "/ingestion/historical" in paths


def test_create_app_returns_a_fresh_instance_each_time():
    app_a = create_app()
    app_b = create_app()
    assert app_a is not app_b
