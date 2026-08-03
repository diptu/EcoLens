import jwt
import pytest

from app.api.v1.dbt import routes as dbt_routes
from app.main import app
from app.core.config import get_settings


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


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


def test_missing_dbt_binary_is_a_real_500(client):
    # No monkeypatching here — exercises the actual FileNotFoundError path
    # in app.service.dbt_runner, since dbt genuinely isn't installed.
    response = client.post("/v1/dbt/build", headers=_auth())

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "internal"
    assert "exit code 127" in body["error"]["message"]
