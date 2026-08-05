from app.api.v1 import deps
from app.api.v1.pipeline import routes as pipeline_routes
from app.retention.size_monitor import SizeReport


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows
        self.executed: list[tuple[str, dict]] = []

    async def execute(self, query, params=None):
        self.executed.append((str(query), params or {}))
        return _FakeResult(self._rows)


def test_status_reports_counts_per_status(client):
    fake_db = _FakeDb([("success", 53), ("staged", 392), ("sync_failed", 2)])

    async def fake_get_db():
        yield fake_db

    client.app.dependency_overrides[deps.get_db] = fake_get_db

    response = client.get("/v1/pipeline/status")

    assert response.status_code == 200
    assert response.json() == {
        "window_hours": 24,
        "success": 53,
        "sync_failed": 2,
        "staged": 392,
    }

    client.app.dependency_overrides.clear()


def test_status_defaults_missing_statuses_to_zero(client):
    fake_db = _FakeDb([])

    async def fake_get_db():
        yield fake_db

    client.app.dependency_overrides[deps.get_db] = fake_get_db

    response = client.get("/v1/pipeline/status")

    assert response.json() == {
        "window_hours": 24,
        "success": 0,
        "sync_failed": 0,
        "staged": 0,
    }

    client.app.dependency_overrides.clear()


def test_status_honours_a_custom_window(client):
    fake_db = _FakeDb([])

    async def fake_get_db():
        yield fake_db

    client.app.dependency_overrides[deps.get_db] = fake_get_db

    response = client.get("/v1/pipeline/status?window_hours=6")

    assert response.json()["window_hours"] == 6
    assert fake_db.executed[0][1]["window_hours"] == 6

    client.app.dependency_overrides.clear()


def test_storage_reports_the_real_database_size(client, monkeypatch):
    async def fake_check_database_size():
        return SizeReport(size_bytes=100, limit_bytes=1000, pct_used=0.1, severity="ok")

    monkeypatch.setattr(
        pipeline_routes, "check_database_size", fake_check_database_size
    )

    response = client.get("/v1/pipeline/storage")

    assert response.status_code == 200
    assert response.json() == {
        "size_bytes": 100,
        "limit_bytes": 1000,
        "pct_used": 0.1,
        "severity": "ok",
    }
