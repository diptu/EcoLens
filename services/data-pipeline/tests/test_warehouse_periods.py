"""Tests for ecolens.warehouse.core.periods."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ecolens.warehouse.core.periods import VALID_PERIODS, resolve_period

NOW = datetime(2026, 5, 31, 12, 0, tzinfo=timezone.utc)


class TestResolvePeriod:
    def test_ytd_current_window_is_jan1_to_now(self):
        w = resolve_period("ytd", now=NOW)
        assert w.current_since == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert w.current_until == NOW

    def test_ytd_previous_window_is_same_elapsed_duration_one_year_earlier(self):
        w = resolve_period("ytd", now=NOW)
        assert w.previous_since == datetime(2025, 1, 1, tzinfo=timezone.utc)
        assert (w.previous_until - w.previous_since) == (
            w.current_until - w.current_since
        )

    def test_qtd_current_window_starts_at_quarter_boundary(self):
        w = resolve_period("qtd", now=NOW)  # May -> Q2 starts April 1
        assert w.current_since == datetime(2026, 4, 1, tzinfo=timezone.utc)
        assert w.current_until == NOW

    def test_qtd_previous_window_same_quarter_last_year(self):
        w = resolve_period("qtd", now=NOW)
        assert w.previous_since == datetime(2025, 4, 1, tzinfo=timezone.utc)
        assert (w.previous_until - w.previous_since) == (
            w.current_until - w.current_since
        )

    def test_30d_windows_are_back_to_back_30_day_spans(self):
        w = resolve_period("30d", now=NOW)
        assert w.current_until == NOW
        assert (w.current_until - w.current_since).days == 30
        assert w.previous_until == w.current_since
        assert (w.previous_until - w.previous_since).days == 30

    def test_7d_windows_are_back_to_back_7_day_spans(self):
        w = resolve_period("7d", now=NOW)
        assert (w.current_until - w.current_since).days == 7
        assert w.previous_until == w.current_since
        assert (w.previous_until - w.previous_since).days == 7

    def test_every_valid_period_resolves_without_error(self):
        for period in VALID_PERIODS:
            w = resolve_period(period, now=NOW)
            assert w.current_since < w.current_until
            assert w.previous_since < w.previous_until

    def test_unknown_period_raises(self):
        with pytest.raises(ValueError):
            resolve_period("bogus", now=NOW)

    def test_defaults_to_real_now_when_omitted(self):
        w = resolve_period("7d")
        assert w.current_until.tzinfo is not None
