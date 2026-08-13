"""`GET /v1/data-quality/summary/public` -- ported from data-pipeline's
`tests/test_data_quality_router.py`'s public-summary coverage only, the
one route this platform's dashboard actually calls."""

from __future__ import annotations

import pytest

from app.api.v1.deps import get_db, get_redis_client
from app.main import app


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, run_rows=()):
        self.run_rows = list(run_rows)

    async def execute(self, query, params=None):
        sql = str(query)
        if "FROM meta._ingest_log l" in sql and "LEFT JOIN" in sql:
            return FakeResult(self.run_rows)
        if "GROUP BY source, metric" in sql:
            return FakeResult([])
        if "FROM meta.schema_drifts ORDER BY first_seen_at" in sql:
            return FakeResult([])
        raise AssertionError(f"unexpected query: {sql}")


class FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        self.store[key] = value
        return True


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


def test_public_summary_requires_no_auth(client):
    app.dependency_overrides[get_db] = lambda: FakeSession()
    app.dependency_overrides[get_redis_client] = lambda: FakeRedis()

    response = client.get("/v1/data-quality/summary/public")

    assert response.status_code != 401
    assert response.status_code != 403
    assert response.status_code == 200


def test_public_summary_returns_only_the_two_aggregate_numbers(client):
    app.dependency_overrides[get_db] = lambda: FakeSession()
    app.dependency_overrides[get_redis_client] = lambda: FakeRedis()

    response = client.get("/v1/data-quality/summary/public")

    body = response.json()
    assert set(body.keys()) == {"as_of", "data_quality_score_pct", "open_risks_high_plus"}
