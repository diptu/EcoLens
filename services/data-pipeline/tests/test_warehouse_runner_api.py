"""Tests for ecolens.warehouse.runner.api -- the /warehouse/run control
surface.

`trigger_warehouse_run` fires a real `WarehouseRunner.run()` in the
background, which needs a live warehouse Postgres + dbt -- out of scope
for a unit test, so those tests just verify the endpoint schedules the
right job function (monkeypatched) with the right arguments and returns
immediately, same pattern as test_forecasting_api.py/test_ingestion_api.py.
`/warehouse/last-run` is tested against a real (temp-dir) JSONL file,
since that's just a file read with no external dependency.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ecolens.warehouse.runner import api as api_module
from ecolens.warehouse.runner.settings import get_warehouse_runner_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    # chdir so WarehouseRunnerSettings' relative log_dir ("data/log")
    # resolves inside tmp_path, not this repo's real data/log -- same
    # reasoning as test_ingestion_api.py's client fixture.
    monkeypatch.chdir(tmp_path)
    get_warehouse_runner_settings.cache_clear()
    api_module._jobs.clear()

    app = FastAPI()
    app.include_router(api_module.router)
    with TestClient(app) as c:
        yield c
    get_warehouse_runner_settings.cache_clear()
    api_module._jobs.clear()


class TestTriggerRun:
    def test_defaults_to_incremental_and_runs_the_job(self, client, monkeypatch):
        captured = {}

        async def fake_job(
            mode, dbt_select, dbt_exclude, skip_aggregates, skip_archive
        ):
            captured.update(
                mode=mode,
                dbt_select=dbt_select,
                dbt_exclude=dbt_exclude,
                skip_aggregates=skip_aggregates,
                skip_archive=skip_archive,
            )
            return {"success": True, "stages": []}

        monkeypatch.setattr(api_module, "_run_pipeline_job", fake_job)
        response = client.post("/warehouse/run")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "started"
        assert body["mode"] == "incremental"
        assert "job_id" in body
        # TestClient runs BackgroundTasks inline, so the fake already ran.
        assert captured == {
            "mode": "incremental",
            "dbt_select": None,
            "dbt_exclude": None,
            "skip_aggregates": False,
            "skip_archive": False,
        }

    def test_passes_through_mode_select_exclude_and_skip_flags(
        self, client, monkeypatch
    ):
        captured = {}

        async def fake_job(
            mode, dbt_select, dbt_exclude, skip_aggregates, skip_archive
        ):
            captured.update(
                mode=mode,
                dbt_select=dbt_select,
                dbt_exclude=dbt_exclude,
                skip_aggregates=skip_aggregates,
                skip_archive=skip_archive,
            )
            return {"success": True, "stages": []}

        monkeypatch.setattr(api_module, "_run_pipeline_job", fake_job)
        response = client.post(
            "/warehouse/run",
            params={
                "mode": "full",
                "select": ["tag:ml_features", "+fact_demand_30min"],
                "exclude": ["tag:dev"],
                "skip_aggregates": True,
                "skip_archive": True,
            },
        )

        assert response.status_code == 200
        assert response.json()["mode"] == "full"
        assert captured == {
            "mode": "full",
            "dbt_select": ["tag:ml_features", "+fact_demand_30min"],
            "dbt_exclude": ["tag:dev"],
            "skip_aggregates": True,
            "skip_archive": True,
        }

    def test_unknown_mode_422s(self, client):
        response = client.post("/warehouse/run", params={"mode": "not_a_real_mode"})
        assert response.status_code == 422


class TestRunStatus:
    def test_poll_after_completion_returns_full_result(self, client, monkeypatch):
        async def fake_job(
            mode, dbt_select, dbt_exclude, skip_aggregates, skip_archive
        ):
            return {
                "success": True,
                "duration_seconds": 1.23,
                "stages": [{"name": "source_freshness", "success": True}],
            }

        monkeypatch.setattr(api_module, "_run_pipeline_job", fake_job)
        job_id = client.post("/warehouse/run", params={"mode": "validate"}).json()[
            "job_id"
        ]

        response = client.get(f"/warehouse/run/{job_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "completed"
        assert body["mode"] == "validate"
        assert body["result"]["success"] is True
        assert body["result"]["stages"][0]["name"] == "source_freshness"
        assert body["error"] is None

    def test_job_that_raises_shows_as_failed(self, client, monkeypatch):
        async def fake_job(
            mode, dbt_select, dbt_exclude, skip_aggregates, skip_archive
        ):
            raise RuntimeError("boom")

        monkeypatch.setattr(api_module, "_run_pipeline_job", fake_job)
        job_id = client.post("/warehouse/run").json()["job_id"]

        response = client.get(f"/warehouse/run/{job_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "failed"
        assert body["error"] == "boom"

    def test_unknown_job_id_404s(self, client):
        response = client.get("/warehouse/run/does-not-exist")
        assert response.status_code == 404


class TestLastRun:
    def test_404s_when_no_runs_recorded_yet(self, client):
        response = client.get("/warehouse/last-run")
        assert response.status_code == 404

    def test_returns_the_most_recently_appended_line(self, client):
        settings = get_warehouse_runner_settings()
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = settings.log_dir / "warehouse-runs.jsonl"
        log_file.write_text(
            json.dumps({"success": False, "duration_seconds": 0.1})
            + "\n"
            + json.dumps({"success": True, "duration_seconds": 42.0})
            + "\n"
        )

        response = client.get("/warehouse/last-run")
        assert response.status_code == 200
        body = response.json()
        assert body["success"] is True
        assert body["duration_seconds"] == 42.0

    def test_ignores_a_trailing_blank_line(self, client):
        settings = get_warehouse_runner_settings()
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        log_file = settings.log_dir / "warehouse-runs.jsonl"
        log_file.write_text(
            json.dumps({"success": True, "duration_seconds": 5.0}) + "\n\n"
        )

        response = client.get("/warehouse/last-run")
        assert response.status_code == 200
        assert response.json()["success"] is True
