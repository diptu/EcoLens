from __future__ import annotations

import jwt
import pytest

from app.main import app
from app.api.v1.deps import get_db
from app.service.auth import hash_password
from app.core.config import get_settings


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeSession:
    def __init__(self, user_row=None):
        self.user_row = user_row

    async def execute(self, query, params=None):
        sql = str(query)
        if sql.strip().startswith("SELECT"):
            return _FakeResult(self.user_row)
        if sql.strip().startswith("UPDATE"):
            return _FakeResult(None)
        raise AssertionError(f"unexpected query: {sql}")


def _user_row(**overrides):
    row = {
        "id": "user-1",
        "username": "diptu",
        "password_hash": hash_password("hunter2"),
        "role": "admin",
        "is_active": True,
    }
    row.update(overrides)
    return row


class TestIssueTokenEndpoint:
    pytestmark = [pytest.mark.anyio]

    def test_success_returns_a_usable_token(self, client):
        app.dependency_overrides[get_db] = lambda: _FakeSession(_user_row())
        try:
            response = client.post(
                "/v1/auth/token", json={"username": "diptu", "password": "hunter2"}
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 200
        body = response.json()
        assert body["token_type"] == "bearer"
        assert body["role"] == "admin"
        assert body["expires_in"] > 0

        settings = get_settings()
        payload = jwt.decode(
            body["access_token"],
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
        assert payload["sub"] == "diptu"
        assert payload["role"] == "admin"

    def test_wrong_password_is_401(self, client):
        app.dependency_overrides[get_db] = lambda: _FakeSession(_user_row())
        try:
            response = client.post(
                "/v1/auth/token", json={"username": "diptu", "password": "wrong"}
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    def test_unknown_username_is_401(self, client):
        app.dependency_overrides[get_db] = lambda: _FakeSession(None)
        try:
            response = client.post(
                "/v1/auth/token", json={"username": "nobody", "password": "hunter2"}
            )
        finally:
            app.dependency_overrides.clear()

        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"

    async def test_issued_token_is_accepted_by_the_real_verifier(self, client):
        from fastapi.security import HTTPAuthorizationCredentials

        from app.core.security import get_current_principal

        app.dependency_overrides[get_db] = lambda: _FakeSession(_user_row())
        try:
            token_response = client.post(
                "/v1/auth/token", json={"username": "diptu", "password": "hunter2"}
            )
            token = token_response.json()["access_token"]
        finally:
            app.dependency_overrides.clear()

        credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
        principal = await get_current_principal(
            credentials=credentials, settings=get_settings()
        )

        assert principal.sub == "diptu"
        assert principal.role == "admin"
