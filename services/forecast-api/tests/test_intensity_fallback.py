from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.service.ml.data import resolve_intensity_method


class TestResolveIntensityMethod:
    def test_falls_back_when_provider_intensity_is_none(self):
        now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)

        method = resolve_intensity_method(now, None, 90.0, now=now)

        assert method == "live_mix_weighted"

    def test_prefers_provider_when_fresh(self):
        now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        hour = now - timedelta(minutes=10)

        method = resolve_intensity_method(hour, 500.0, 90.0, now=now)

        assert method == "live_provider"

    def test_falls_back_when_provider_is_stale(self):
        now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        hour = now - timedelta(minutes=200)

        method = resolve_intensity_method(hour, 500.0, 90.0, now=now)

        assert method == "live_mix_weighted"

    def test_boundary_at_exactly_the_freshness_threshold_is_fresh(self):
        now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        hour = now - timedelta(minutes=90)

        method = resolve_intensity_method(hour, 500.0, 90.0, now=now)

        assert method == "live_provider"

    def test_handles_naive_hour_as_utc(self):
        now = datetime(2026, 8, 4, 12, 0, tzinfo=UTC)
        naive_hour = datetime(2026, 8, 4, 11, 50)  # no tzinfo

        method = resolve_intensity_method(naive_hour, 500.0, 90.0, now=now)

        assert method == "live_provider"

    def test_defaults_now_to_the_real_current_time_when_not_given(self):
        recent_hour = datetime.now(UTC) - timedelta(minutes=5)

        method = resolve_intensity_method(recent_hour, 500.0, 90.0)

        assert method == "live_provider"
