from __future__ import annotations

import pytest

from app.service.ml.adaptive_calibration import (
    DEFAULT_SCALE,
    MAX_SCALE,
    MIN_SCALE,
    calibration_scale_key,
    get_calibration_scale,
    update_calibration_scale,
)

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key):
        return self.store.get(key)

    async def set(self, key, value, ex=None, nx=None):
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True


class TestGetCalibrationScale:
    async def test_defaults_to_unscaled_when_never_set(self):
        redis = _FakeRedis()
        assert await get_calibration_scale(redis, "lstm_demand", "NSW1") == DEFAULT_SCALE

    async def test_reads_back_a_previously_stored_scale(self):
        redis = _FakeRedis()
        redis.store[calibration_scale_key("lstm_demand", "NSW1")] = "1.5"
        assert await get_calibration_scale(redis, "lstm_demand", "NSW1") == 1.5


class TestUpdateCalibrationScale:
    async def test_a_miss_nudges_the_scale_up(self):
        redis = _FakeRedis()
        updated = await update_calibration_scale(
            redis, model_name="lstm_demand", region="NSW1",
            covered=False, target_alpha=0.2,
        )
        assert updated > DEFAULT_SCALE

    async def test_a_hit_nudges_the_scale_down(self):
        redis = _FakeRedis()
        updated = await update_calibration_scale(
            redis, model_name="lstm_demand", region="NSW1",
            covered=True, target_alpha=0.2,
        )
        assert updated < DEFAULT_SCALE

    async def test_repeated_misses_clamp_at_the_max_scale(self):
        redis = _FakeRedis()
        scale = DEFAULT_SCALE
        for _ in range(1000):
            scale = await update_calibration_scale(
                redis, model_name="lstm_demand", region="NSW1",
                covered=False, target_alpha=0.2, step_size=0.5,
            )
        assert scale == MAX_SCALE

    async def test_repeated_hits_clamp_at_the_min_scale(self):
        redis = _FakeRedis()
        scale = DEFAULT_SCALE
        for _ in range(1000):
            scale = await update_calibration_scale(
                redis, model_name="lstm_demand", region="NSW1",
                covered=True, target_alpha=0.2, step_size=0.5,
            )
        assert scale == MIN_SCALE

    async def test_persists_the_updated_scale_for_the_next_read(self):
        redis = _FakeRedis()
        updated = await update_calibration_scale(
            redis, model_name="lstm_demand", region="NSW1",
            covered=False, target_alpha=0.2,
        )
        assert await get_calibration_scale(redis, "lstm_demand", "NSW1") == updated

    async def test_scales_are_tracked_independently_per_model_and_region(self):
        redis = _FakeRedis()
        await update_calibration_scale(
            redis, model_name="lstm_demand", region="NSW1",
            covered=False, target_alpha=0.2,
        )
        assert await get_calibration_scale(redis, "lstm_demand", "QLD1") == DEFAULT_SCALE
