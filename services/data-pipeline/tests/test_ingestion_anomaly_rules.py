"""Tests for ecolens.ingestion.service.anomaly.rules (root TODO.md's
"Anomaly Detection" section, rule-based layer).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ecolens.ingestion.core.settings import IngestionSettings
from ecolens.ingestion.service.anomaly.rules import evaluate_rules


@pytest.fixture
def settings() -> IngestionSettings:
    return IngestionSettings()


def _nem_doc(**overrides) -> dict:
    doc = {
        "region": "NSW1",
        "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "fetched_at": datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        "demand_mw": 6000.0,
        "price_mwh": 80.0,
    }
    doc.update(overrides)
    return doc


def _bom_doc(**overrides) -> dict:
    doc = {
        "station_id": "066037",
        "ts": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "fetched_at": datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        "temp_c": 22.0,
        "humidity_pct": 55.0,
        "wind_speed_kmh": 15.0,
    }
    doc.update(overrides)
    return doc


class TestPriceRange:
    def test_normal_price_does_not_fire(self, settings):
        flags = {
            r.flag for r in evaluate_rules("aemo_nem", _nem_doc(), settings=settings)
        }
        assert "rule:price_above_cap" not in flags
        assert "rule:price_below_floor" not in flags

    def test_price_above_cap_fires(self, settings):
        results = evaluate_rules(
            "aemo_nem", _nem_doc(price_mwh=20_000.0), settings=settings
        )
        assert any(r.flag == "rule:price_above_cap" for r in results)

    def test_price_below_floor_fires(self, settings):
        results = evaluate_rules(
            "aemo_nem", _nem_doc(price_mwh=-2_000.0), settings=settings
        )
        assert any(r.flag == "rule:price_below_floor" for r in results)

    def test_null_price_does_not_fire(self, settings):
        results = evaluate_rules(
            "aemo_nem", _nem_doc(price_mwh=None), settings=settings
        )
        assert not any(
            r.flag in ("rule:price_above_cap", "rule:price_below_floor")
            for r in results
        )


class TestDemandNegative:
    def test_positive_demand_does_not_fire(self, settings):
        results = evaluate_rules(
            "aemo_nem", _nem_doc(demand_mw=5000.0), settings=settings
        )
        assert not any(r.flag == "rule:demand_negative" for r in results)

    def test_negative_demand_fires(self, settings):
        results = evaluate_rules(
            "aemo_nem", _nem_doc(demand_mw=-100.0), settings=settings
        )
        assert any(r.flag == "rule:demand_negative" for r in results)


class TestDemandSuddenJump:
    def test_no_prev_doc_does_not_fire(self, settings):
        results = evaluate_rules(
            "aemo_nem", _nem_doc(), prev_doc=None, settings=settings
        )
        assert not any(r.flag == "rule:demand_sudden_jump" for r in results)

    def test_small_change_does_not_fire(self, settings):
        prev = _nem_doc(demand_mw=6000.0)
        curr = _nem_doc(demand_mw=6200.0)
        results = evaluate_rules("aemo_nem", curr, prev_doc=prev, settings=settings)
        assert not any(r.flag == "rule:demand_sudden_jump" for r in results)

    def test_large_jump_fires(self, settings):
        prev = _nem_doc(demand_mw=6000.0)
        curr = _nem_doc(demand_mw=15000.0)
        results = evaluate_rules("aemo_nem", curr, prev_doc=prev, settings=settings)
        assert any(r.flag == "rule:demand_sudden_jump" for r in results)

    def test_zero_prev_demand_does_not_divide_by_zero(self, settings):
        prev = _nem_doc(demand_mw=0.0)
        curr = _nem_doc(demand_mw=500.0)
        results = evaluate_rules("aemo_nem", curr, prev_doc=prev, settings=settings)
        assert not any(r.flag == "rule:demand_sudden_jump" for r in results)


class TestBomRanges:
    def test_normal_readings_do_not_fire(self, settings):
        results = evaluate_rules("bom", _bom_doc(), settings=settings)
        assert results == []

    def test_temp_out_of_range_fires(self, settings):
        results = evaluate_rules("bom", _bom_doc(temp_c=90.0), settings=settings)
        assert any(r.flag == "rule:temp_out_of_range" for r in results)

    def test_temp_below_range_fires(self, settings):
        results = evaluate_rules("bom", _bom_doc(temp_c=-50.0), settings=settings)
        assert any(r.flag == "rule:temp_out_of_range" for r in results)

    def test_humidity_out_of_range_fires(self, settings):
        results = evaluate_rules("bom", _bom_doc(humidity_pct=150.0), settings=settings)
        assert any(r.flag == "rule:humidity_out_of_range" for r in results)

    def test_wind_speed_out_of_range_fires(self, settings):
        results = evaluate_rules(
            "bom", _bom_doc(wind_speed_kmh=-5.0), settings=settings
        )
        assert any(r.flag == "rule:wind_speed_out_of_range" for r in results)

    def test_multiple_bom_violations_all_fire(self, settings):
        results = evaluate_rules(
            "bom", _bom_doc(temp_c=90.0, humidity_pct=150.0), settings=settings
        )
        flags = {r.flag for r in results}
        assert "rule:temp_out_of_range" in flags
        assert "rule:humidity_out_of_range" in flags


class TestCompleteness:
    def test_complete_nem_record_does_not_fire(self, settings):
        results = evaluate_rules("aemo_nem", _nem_doc(), settings=settings)
        assert not any(r.flag == "rule:incomplete_record" for r in results)

    def test_missing_price_fires(self, settings):
        results = evaluate_rules(
            "aemo_nem", _nem_doc(price_mwh=None), settings=settings
        )
        fired = [r for r in results if r.flag == "rule:incomplete_record"]
        assert len(fired) == 1
        assert "price_mwh" in fired[0].detail

    def test_holidays_has_no_completeness_rule(self, settings):
        # aemo_holidays has no metric_columns_for_source -- nothing to
        # flag as incomplete.
        results = evaluate_rules(
            "aemo_holidays",
            {
                "region": "NSW1",
                "date": "2026-01-01",
                "fetched_at": datetime.now(timezone.utc),
            },
            settings=settings,
        )
        assert not any(r.flag == "rule:incomplete_record" for r in results)


class TestStaleness:
    def test_fresh_record_does_not_fire(self, settings):
        results = evaluate_rules("aemo_wem", _nem_doc(), settings=settings)
        assert not any(r.flag == "rule:stale_record" for r in results)

    def test_stale_record_fires(self, settings):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        doc = _nem_doc(ts=ts, fetched_at=ts + timedelta(hours=10))
        results = evaluate_rules("aemo_wem", doc, settings=settings)
        assert any(r.flag == "rule:stale_record" for r in results)

    def test_aemo_nem_tolerates_its_known_publish_lag(self, settings):
        # AEMO NEM's own ~4am-next-day publish quirk -- a lag that would
        # be "stale" for WEM must not fire for NEM, since its threshold
        # is deliberately much more generous.
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        doc = _nem_doc(ts=ts, fetched_at=ts + timedelta(hours=20))
        results = evaluate_rules("aemo_nem", doc, settings=settings)
        assert not any(r.flag == "rule:stale_record" for r in results)

    def test_holidays_never_flagged_stale(self, settings):
        # date is often legitimately far from fetched_at by design.
        doc = {
            "region": "NSW1",
            "date": "2026-12-25",
            "fetched_at": datetime.now(timezone.utc),
        }
        results = evaluate_rules("aemo_holidays", doc, settings=settings)
        assert not any(r.flag == "rule:stale_record" for r in results)

    def test_ts_as_iso_string_is_handled(self, settings):
        doc = _nem_doc(ts="2026-01-01T00:00:00Z", fetched_at="2026-01-01T10:00:00Z")
        results = evaluate_rules("aemo_wem", doc, settings=settings)
        assert any(r.flag == "rule:stale_record" for r in results)
