"""Password hashing, credential verification, and JWT issuance backing
`POST /v1/auth/token` and `ecolens-pipeline auth create-user`.

**What this is not**: a full IAM system. There's no refresh-token flow
(access tokens just expire — `Settings.jwt_access_token_expires_seconds`,
default 1h — and the caller re-authenticates), no per-source/per-team
scoping beyond the existing `admin`/`analyst` roles, and no audit log
beyond `last_login_at`. Real, deliberate scope limits — see `TODO.md`'s
IAM section for what's tracked as still open.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ROLES
from app.core.config import Settings

# bcrypt's own recommended default as of this writing -- high enough to
# be slow for an offline brute-force attempt against a leaked hash, low
# enough not to make login latency noticeable.
_BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(
        password.encode("utf-8"), bcrypt.gensalt(_BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # A malformed hash never happens for one this module wrote itself,
        # but a hand-edited/corrupted row shouldn't crash the login
        # attempt -- just fail it, same as a wrong password would.
        return False


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    username: str
    role: str


async def authenticate(
    db: AsyncSession, username: str, password: str
) -> AuthenticatedUser | None:
    """`None` on unknown username, wrong password, *or* an inactive
    account -- deliberately indistinguishable from the caller's side, so
    a failed-login response can't be used to enumerate valid usernames."""
    result = await db.execute(
        text(
            "SELECT id, username, password_hash, role, is_active "
            "FROM meta.api_users WHERE username = :username"
        ),
        {"username": username},
    )
    row = result.mappings().first()
    if row is None or not row["is_active"]:
        return None
    if not verify_password(password, row["password_hash"]):
        return None

    await db.execute(
        text("UPDATE meta.api_users SET last_login_at = now() WHERE id = :id"),
        {"id": row["id"]},
    )
    return AuthenticatedUser(
        id=str(row["id"]), username=row["username"], role=row["role"]
    )


def issue_token(user: AuthenticatedUser, settings: Settings) -> tuple[str, int]:
    """Returns `(token, expires_in_seconds)`. `exp`/`iat` are real claims
    -- `app.core.security.get_current_principal`'s `jwt.decode` already
    verifies `exp` when present (PyJWT's default), so this is enough to
    make issued tokens actually expire without touching the verifier."""
    now = datetime.now(UTC)
    expires_in = settings.jwt_access_token_expires_seconds
    payload = {
        "sub": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


async def create_user(db: AsyncSession, username: str, password: str, role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}, got {role!r}")
    result = await db.execute(
        text(
            "INSERT INTO meta.api_users (username, password_hash, role) "
            "VALUES (:username, :password_hash, :role) "
            "RETURNING id"
        ),
        {"username": username, "password_hash": hash_password(password), "role": role},
    )
    row = result.first()
    assert (  # nosec B101 -- internal invariant for type-narrowing, not a security check; INSERT ... RETURNING always returns the row it just inserted
        row is not None
    )
    return str(row[0])
