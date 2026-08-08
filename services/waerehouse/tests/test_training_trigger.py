import pytest

from app.dbt import training_trigger

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeMappingsResult:
    def __init__(self, row):
        self._row = row


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeDb:
    def __init__(self, anomaly_count: int):
        self._anomaly_count = anomaly_count
        self.executed: list[str] = []

    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _FakeResult((self._anomaly_count,))


class _FakeSessionCtx:
    def __init__(self, db):
        self._db = db

    async def __aenter__(self):
        return self._db

    async def __aexit__(self, *exc_info):
        return False


def _wire_session(monkeypatch, anomaly_count: int = 0):
    fake_db = _FakeDb(anomaly_count)

    def fake_get_session():
        return _FakeSessionCtx(fake_db)

    monkeypatch.setattr(training_trigger, "get_session", fake_get_session)
    return fake_db


class TestPublishTrainingTrigger:
    async def test_builds_and_publishes_the_expected_payload_shape(self, monkeypatch):
        _wire_session(monkeypatch, anomaly_count=3)
        published = []

        async def fake_publish(payload):
            published.append(payload)

        monkeypatch.setattr(training_trigger, "publish_training_trigger_event", fake_publish)

        payload = await training_trigger.publish_training_trigger(
            ["NSW1"], 24, architecture="tft", triggered_by="dashboard"
        )

        assert payload["event"] == "warehouse.transform.completed"
        assert payload["dataset"] == "raw_marts.fct_energy_demand"
        assert payload["regions"] == ["NSW1"]
        assert payload["architecture"] == "tft"
        assert payload["triggered_by"] == "dashboard"
        assert payload["anomalies_flagged"] == 3
        assert published == [payload]

    async def test_defaults_to_lstm_and_schedule(self, monkeypatch):
        _wire_session(monkeypatch)
        published = []

        async def fake_publish(payload):
            published.append(payload)

        monkeypatch.setattr(training_trigger, "publish_training_trigger_event", fake_publish)

        payload = await training_trigger.publish_training_trigger(["NSW1"], 24)

        assert payload["architecture"] == "lstm"
        assert payload["triggered_by"] == "schedule"


class TestPublishTrainingTriggersForBuild:
    async def test_publishes_once_per_incremental_architecture(self, monkeypatch):
        _wire_session(monkeypatch)
        published = []

        async def fake_publish(payload):
            published.append(payload)

        monkeypatch.setattr(training_trigger, "publish_training_trigger_event", fake_publish)

        results = await training_trigger.publish_training_triggers_for_build(
            triggered_by="dashboard"
        )

        architectures = {p["architecture"] for p in results}
        assert architectures == set(training_trigger.INCREMENTAL_ARCHITECTURES)
        assert len(results) == len(training_trigger.INCREMENTAL_ARCHITECTURES)
        assert all(p["triggered_by"] == "dashboard" for p in results)

    async def test_one_failed_publish_does_not_stop_the_others(self, monkeypatch):
        """A broken publish for one architecture must not prevent the
        other architecture's trigger from firing, and must not raise --
        the `dbt build` already succeeded and is already logged
        regardless of whether the downstream event makes it out."""
        _wire_session(monkeypatch)
        calls = []

        async def flaky_publish(payload):
            calls.append(payload["architecture"])
            if payload["architecture"] == "lstm":
                raise ConnectionError("rabbitmq unreachable")

        monkeypatch.setattr(training_trigger, "publish_training_trigger_event", flaky_publish)

        results = await training_trigger.publish_training_triggers_for_build()

        assert set(calls) == set(training_trigger.INCREMENTAL_ARCHITECTURES)
        assert len(results) == len(training_trigger.INCREMENTAL_ARCHITECTURES) - 1
        assert all(p["architecture"] != "lstm" for p in results)
