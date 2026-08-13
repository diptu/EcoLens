from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.service.ml.adaptive_calibration import get_calibration_scale
from app.service.ml.forecast_breaker import ForecastCircuitBreaker
from app.service.ml.forecast_reconciliation import (
    breaker_name,
    record_served_forecast,
    reconcile_pending_forecasts,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    async def delete(self, *keys):
        for key in keys:
            self.store.pop(key, None)

    async def incr(self, key):
        current = int(self.store.get(key, 0))
        current += 1
        self.store[key] = str(current)
        return current

    async def hset(self, key, field, value):
        self.hashes.setdefault(key, {})[field] = value

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hdel(self, key, field):
        self.hashes.get(key, {}).pop(field, None)

    async def expire(self, key, seconds):
        pass


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _FakeDb:
    def __init__(self, demand_by_ts: dict[datetime, float]):
        self._demand_by_ts = demand_by_ts

    async def execute(self, query, params=None):
        ts = params["ts"]
        value = self._demand_by_ts.get(ts)
        return _FakeResult((value,) if value is not None else None)


NOW = datetime(2026, 1, 2, tzinfo=UTC)


class TestRecordServedForecast:
    async def test_writes_a_hash_field_keyed_by_target_ts(self):
        redis = _FakeRedis()
        target_ts = NOW - timedelta(hours=1)

        await record_served_forecast(
            redis,
            model_name="lstm_demand",
            region="NSW1",
            target_ts=target_ts,
            p50_mw=5000.0,
            p10_mw=4500.0,
            p90_mw=5500.0,
        )

        key = "forecast_served:lstm_demand:NSW1"
        assert key in redis.hashes
        (value,) = redis.hashes[key].values()
        assert json.loads(value)["p50_mw"] == 5000.0
        assert json.loads(value)["p10_mw"] == 4500.0
        assert json.loads(value)["p90_mw"] == 5500.0

    async def test_a_second_call_for_the_same_target_overwrites(self):
        redis = _FakeRedis()
        target_ts = NOW - timedelta(hours=1)

        await record_served_forecast(
            redis, model_name="lstm_demand", region="NSW1",
            target_ts=target_ts, p50_mw=5000.0, p10_mw=4500.0, p90_mw=5500.0,
        )
        await record_served_forecast(
            redis, model_name="lstm_demand", region="NSW1",
            target_ts=target_ts, p50_mw=5200.0, p10_mw=4700.0, p90_mw=5700.0,
        )

        key = "forecast_served:lstm_demand:NSW1"
        assert len(redis.hashes[key]) == 1
        (value,) = redis.hashes[key].values()
        assert json.loads(value)["p50_mw"] == 5200.0


class TestReconcilePendingForecasts:
    async def test_a_close_prediction_records_a_success(self):
        redis = _FakeRedis()
        target_ts = NOW - timedelta(hours=1)
        await record_served_forecast(
            redis, model_name="lstm_demand", region="NSW1",
            target_ts=target_ts, p50_mw=5000.0, p10_mw=4500.0, p90_mw=5500.0,
        )
        db = _FakeDb({target_ts: 5100.0})  # 2% error, well under threshold

        result = await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1", now=NOW
        )

        assert result.reconciled == 1
        assert result.successes == 1
        assert result.failures == 0
        state = await ForecastCircuitBreaker(
            breaker_name("lstm_demand", "NSW1"), redis
        ).state
        assert state.value == "closed"

    async def test_a_wildly_wrong_prediction_records_a_failure(self):
        redis = _FakeRedis()
        target_ts = NOW - timedelta(hours=1)
        await record_served_forecast(
            redis, model_name="lstm_demand", region="NSW1",
            target_ts=target_ts, p50_mw=5000.0, p10_mw=4500.0, p90_mw=5500.0,
        )
        db = _FakeDb({target_ts: 8000.0})  # 37.5% error

        result = await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1",
            error_threshold_pct=15.0, now=NOW,
        )

        assert result.failures == 1
        assert result.successes == 0

    async def test_enough_failures_actually_open_the_breaker(self):
        redis = _FakeRedis()
        for i in range(5):
            target_ts = NOW - timedelta(hours=i + 1)
            await record_served_forecast(
                redis, model_name="lstm_demand", region="NSW1",
                target_ts=target_ts, p50_mw=5000.0, p10_mw=4500.0, p90_mw=5500.0,
            )
        db = _FakeDb({NOW - timedelta(hours=i + 1): 9000.0 for i in range(5)})

        await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1", now=NOW
        )

        state = await ForecastCircuitBreaker(
            breaker_name("lstm_demand", "NSW1"), redis
        ).state
        assert state.value == "open"

    async def test_a_future_target_ts_is_left_pending_not_reconciled(self):
        redis = _FakeRedis()
        future_ts = NOW + timedelta(hours=1)
        await record_served_forecast(
            redis, model_name="lstm_demand", region="NSW1",
            target_ts=future_ts, p50_mw=5000.0, p10_mw=4500.0, p90_mw=5500.0,
        )
        db = _FakeDb({})

        result = await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1", now=NOW
        )

        assert result.reconciled == 0
        assert result.still_pending == 1
        # Not removed -- still there to reconcile once it's actually due.
        assert len(redis.hashes["forecast_served:lstm_demand:NSW1"]) == 1

    async def test_missing_real_demand_leaves_the_entry_for_a_later_pass(self):
        redis = _FakeRedis()
        target_ts = NOW - timedelta(hours=1)
        await record_served_forecast(
            redis, model_name="lstm_demand", region="NSW1",
            target_ts=target_ts, p50_mw=5000.0, p10_mw=4500.0, p90_mw=5500.0,
        )
        db = _FakeDb({})  # warehouse hasn't landed this timestamp yet

        result = await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1", now=NOW
        )

        assert result.reconciled == 0
        assert result.still_pending == 1
        assert len(redis.hashes["forecast_served:lstm_demand:NSW1"]) == 1

    async def test_no_pending_entries_is_a_real_noop(self):
        redis = _FakeRedis()
        db = _FakeDb({})

        result = await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1", now=NOW
        )

        assert result.reconciled == 0
        assert result.still_pending == 0

    async def test_a_real_value_inside_the_served_interval_counts_as_covered(self):
        redis = _FakeRedis()
        target_ts = NOW - timedelta(hours=1)
        await record_served_forecast(
            redis, model_name="lstm_demand", region="NSW1",
            target_ts=target_ts, p50_mw=5000.0, p10_mw=4500.0, p90_mw=5500.0,
        )
        db = _FakeDb({target_ts: 5100.0})  # inside [4500, 5500]

        result = await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1", now=NOW
        )

        assert result.coverage_checked == 1
        assert result.covered == 1
        scale = await get_calibration_scale(redis, "lstm_demand", "NSW1")
        # A covered outcome nudges the scale *down* toward 1.0 (below it,
        # in fact, since `target_alpha` misses are expected even on a
        # well-calibrated model) -- never up.
        assert scale < 1.0

    async def test_a_real_value_outside_the_served_interval_counts_as_not_covered(self):
        redis = _FakeRedis()
        target_ts = NOW - timedelta(hours=1)
        await record_served_forecast(
            redis, model_name="lstm_demand", region="NSW1",
            target_ts=target_ts, p50_mw=5000.0, p10_mw=4500.0, p90_mw=5500.0,
        )
        db = _FakeDb({target_ts: 6000.0})  # outside [4500, 5500]

        result = await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1", now=NOW
        )

        assert result.coverage_checked == 1
        assert result.covered == 0
        scale = await get_calibration_scale(redis, "lstm_demand", "NSW1")
        assert scale > 1.0

    async def test_an_entry_missing_p10_p90_skips_the_coverage_update(self):
        """A Redis hash entry from before `p10_mw`/`p90_mw` existed (or
        any payload missing them) must not raise -- it just can't drive
        the adaptive-calibration update, same as any other optional
        signal this reconciliation pass can't compute for a given entry."""
        redis = _FakeRedis()
        target_ts = NOW - timedelta(hours=1)
        key = "forecast_served:lstm_demand:NSW1"
        redis.hashes[key] = {
            target_ts.isoformat(): json.dumps(
                {"p50_mw": 5000.0, "served_at": NOW.isoformat()}
            )
        }
        db = _FakeDb({target_ts: 5100.0})

        result = await reconcile_pending_forecasts(
            redis, db, model_name="lstm_demand", region="NSW1", now=NOW
        )

        assert result.reconciled == 1
        assert result.coverage_checked == 0
        assert result.covered == 0
