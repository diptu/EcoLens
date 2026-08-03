from __future__ import annotations

from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.service.auth import (
    AuthenticatedUser,
    authenticate,
    create_user,
    hash_password,
    issue_token,
    verify_password,
)
from app.core.config import Settings

pytestmark = pytest.mark.anyio


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
    def __init__(self, user_row=None, created_id="new-id"):
        self.user_row = user_row
        self.created_id = created_id
        self.queries: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        sql = str(query)
        params = params or {}
        self.queries.append((sql, params))
        if sql.strip().startswith("SELECT"):
            return _FakeResult(self.user_row)
        if sql.strip().startswith("UPDATE"):
            return _FakeResult(None)
        if sql.strip().startswith("INSERT"):
            return _FakeResult((self.created_id,))
        raise AssertionError(f"unexpected query: {sql}")


class TestPasswordHashing:
    def test_verify_accepts_the_matching_password(self):
        hashed = hash_password("correct horse battery staple")

        assert verify_password("correct horse battery staple", hashed) is True

    def test_verify_rejects_the_wrong_password(self):
        hashed = hash_password("correct horse battery staple")

        assert verify_password("wrong password", hashed) is False

    def test_verify_returns_false_for_a_malformed_hash_instead_of_raising(self):
        assert verify_password("anything", "not-a-real-bcrypt-hash") is False

    def test_hashes_are_salted_differently_each_time(self):
        h1 = hash_password("same password")
        h2 = hash_password("same password")

        assert h1 != h2
        assert verify_password("same password", h1)
        assert verify_password("same password", h2)


class TestAuthenticate:
    async def test_succeeds_for_correct_credentials(self):
        session = _FakeSession(
            user_row={
                "id": "user-1",
                "username": "diptu",
                "password_hash": hash_password("hunter2"),
                "role": "admin",
                "is_active": True,
            }
        )

        user = await authenticate(session, "diptu", "hunter2")

        assert user == AuthenticatedUser(id="user-1", username="diptu", role="admin")
        update_calls = [q for q, _ in session.queries if q.strip().startswith("UPDATE")]
        assert len(update_calls) == 1

    async def test_fails_for_unknown_username(self):
        session = _FakeSession(user_row=None)

        user = await authenticate(session, "nobody", "hunter2")

        assert user is None

    async def test_fails_for_wrong_password(self):
        session = _FakeSession(
            user_row={
                "id": "user-1",
                "username": "diptu",
                "password_hash": hash_password("hunter2"),
                "role": "admin",
                "is_active": True,
            }
        )

        user = await authenticate(session, "diptu", "wrong")

        assert user is None

    async def test_fails_for_inactive_account_even_with_correct_password(self):
        session = _FakeSession(
            user_row={
                "id": "user-1",
                "username": "diptu",
                "password_hash": hash_password("hunter2"),
                "role": "admin",
                "is_active": False,
            }
        )

        user = await authenticate(session, "diptu", "hunter2")

        assert user is None


class TestIssueToken:
    def test_token_decodes_with_expected_claims(self):
        settings = Settings(
            jwt_secret="test-secret", jwt_access_token_expires_seconds=1800
        )
        user = AuthenticatedUser(id="user-1", username="diptu", role="admin")

        token, expires_in = issue_token(user, settings)

        assert expires_in == 1800
        payload = jwt.decode(token, "test-secret", algorithms=["HS256"])
        assert payload["sub"] == "diptu"
        assert payload["role"] == "admin"
        assert "exp" in payload and "iat" in payload

    def test_expired_token_fails_verification(self):
        settings = Settings(
            jwt_secret="test-secret", jwt_access_token_expires_seconds=1800
        )
        user = AuthenticatedUser(id="user-1", username="diptu", role="admin")
        token, _ = issue_token(user, settings)

        # Simulate time passing well beyond expiry by decoding with a
        # leeway of 0 against a manually-crafted already-expired token,
        # rather than sleeping in the test.
        now = datetime.now(UTC)
        expired_payload = {
            "sub": "diptu",
            "role": "admin",
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        }
        expired_token = jwt.encode(expired_payload, "test-secret", algorithm="HS256")

        with pytest.raises(jwt.ExpiredSignatureError):
            jwt.decode(expired_token, "test-secret", algorithms=["HS256"])


class TestCreateUser:
    async def test_inserts_a_hashed_password_and_returns_the_id(self):
        session = _FakeSession(created_id="new-user-id")

        user_id = await create_user(session, "newuser", "hunter2", "analyst")

        assert user_id == "new-user-id"
        insert_sql, params = next(
            (q, p) for q, p in session.queries if q.strip().startswith("INSERT")
        )
        assert params["username"] == "newuser"
        assert params["role"] == "analyst"
        assert params["password_hash"] != "hunter2"  # never stores the plaintext
        assert verify_password("hunter2", params["password_hash"])

    async def test_rejects_an_invalid_role(self):
        session = _FakeSession()

        with pytest.raises(ValueError, match="role must be one of"):
            await create_user(session, "newuser", "hunter2", "superadmin")
