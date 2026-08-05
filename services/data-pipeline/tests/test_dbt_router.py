import jwt
import pytest

from app.api.v1.dbt import routes as dbt_routes
from app.main import app
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def fake_build_log(monkeypatch):
    """`POST /v1/dbt/{subcommand}` now writes `meta._dbt_build_log` rows
    directly (TODO.md's backfill section Follow-up item) -- fake the
    writes for every test in this module so none of them need a real
    Postgres, same pattern as `test_training_worker.py`'s `fake_training_
    log_session`."""

    async def fake_start(**kwargs):
        return "fake-log-id"

    async def fake_finish(log_id, **kwargs):
        return None

    monkeypatch.setattr(dbt_routes, "log_dbt_build_start", fake_start)
    monkeypatch.setattr(dbt_routes, "log_dbt_build_finish", fake_finish)


def _token(role: str, sub: str = "diptu") -> str:
    settings = get_settings()
    return jwt.encode(
        {"sub": sub, "role": role},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def _auth(role: str = "admin", sub: str = "diptu") -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(role, sub)}"}


def test_requires_auth(client):
    response = client.post("/v1/dbt/build")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_analyst_role_is_forbidden(client):
    response = client.post("/v1/dbt/build", headers=_auth("analyst"))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_successful_subcommand_returns_200(client, monkeypatch):
    monkeypatch.setattr(dbt_routes, "run_dbt", lambda *a, **k: 0)

    response = client.post("/v1/dbt/build", headers=_auth())

    assert response.status_code == 200
    body = response.json()
    assert body == {"subcommand": "build", "target": "prod", "exit_code": 0}


def test_failed_subcommand_returns_500(client, monkeypatch):
    monkeypatch.setattr(dbt_routes, "run_dbt", lambda *a, **k: 1)

    response = client.post("/v1/dbt/test", headers=_auth())

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal"
    assert "exit code 1" in body["error"]["message"]


def test_invalid_subcommand_returns_422(client):
    response = client.post("/v1/dbt/nonsense", headers=_auth())

    assert response.status_code == 422


def test_request_body_target_overrides_settings_default(client, monkeypatch):
    captured = {}

    def fake_run_dbt(subcommand, project_dir, target, extra_args):
        captured["target"] = target
        captured["extra_args"] = extra_args
        return 0

    monkeypatch.setattr(dbt_routes, "run_dbt", fake_run_dbt)

    response = client.post(
        "/v1/dbt/run",
        json={"target": "dev", "extra_args": ["--select", "stg_aemo_nem"]},
        headers=_auth(),
    )

    assert response.status_code == 200
    assert response.json()["target"] == "dev"
    assert captured["target"] == "dev"
    assert captured["extra_args"] == ["--select", "stg_aemo_nem"]


def test_missing_dbt_binary_is_a_real_500(client, monkeypatch):
    # `dbt-core` is a real dependency as of `todo-model-training.md` Phase
    # 0 (it used to genuinely be absent, which is what this test relied
    # on) — simulate the missing-binary path the same way
    # `test_dbt_runner.py`'s own unit test does, at the `subprocess.run`
    # level, so this still exercises `dbt_runner.run_dbt`'s real
    # `FileNotFoundError` -> exit-code-127 handling end to end through the
    # route.
    import app.service.dbt_runner as dbt_runner_module

    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(dbt_runner_module.subprocess, "run", fake_run)

    response = client.post("/v1/dbt/build", headers=_auth())

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal"
    assert "exit code 127" in body["error"]["message"]


class TestGetDbtBuildRuns:
    """`GET /v1/dbt/runs` -- real `meta._dbt_build_log` history (TODO.md's
    backfill section Follow-up item). Open, unlike the admin-gated
    subcommand routes above -- read access to run history isn't the
    privileged part."""

    def test_no_auth_required(self, client, monkeypatch):
        from app.api.v1 import deps as v1_deps

        async def fake_list_runs(db, limit):
            return []

        monkeypatch.setattr(dbt_routes, "list_dbt_build_runs", fake_list_runs)
        app.dependency_overrides[v1_deps.get_db] = lambda: object()
        try:
            response = client.get("/v1/dbt/runs")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        assert response.json() == {"data": []}

    def test_returns_mapped_rows(self, client, monkeypatch):
        from app.api.v1 import deps as v1_deps
        from app.schemas.dbt import DbtBuildRunOut

        async def fake_list_runs(db, limit):
            assert limit == 20
            return [
                DbtBuildRunOut(
                    id="11111111-1111-1111-1111-111111111111",
                    subcommand="build",
                    target="prod",
                    trigger="dashboard_manual",
                    triggered_by="dashboard",
                    status="success",
                    started_at="2026-01-01T00:00:00Z",
                    finished_at="2026-01-01T00:05:00Z",
                    exit_code=0,
                    error=None,
                )
            ]

        monkeypatch.setattr(dbt_routes, "list_dbt_build_runs", fake_list_runs)
        app.dependency_overrides[v1_deps.get_db] = lambda: object()
        try:
            response = client.get("/v1/dbt/runs")
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert len(body["data"]) == 1
        assert body["data"][0]["trigger"] == "dashboard_manual"
        assert body["data"][0]["status"] == "success"
