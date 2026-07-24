"""Unit tests for ecolens.ingestion.sources.holidays.transformers."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from ecolens.ingestion.sources.holidays.schema import (
    HOLIDAY_OUTPUT_COLUMNS,
    NEM_REGIONS,
    VALID_HOLIDAY_TYPES,
    VALID_STATES,
)
from ecolens.ingestion.sources.holidays.transformers import (
    apply_data_quality_fixes,
    attach_days_until,
    easter_date,
    synthetic_stub,
)


def _make_doc(**overrides) -> dict:
    base = {
        "date": "2026-01-01",
        "region": "NSW1",
        "state": "NSW",
        "holiday_name": "New Year's Day",
        "holiday_type": "national",
        "schema_version": "1.0",
        "is_business_day": False,
        "is_observed": False,
        "observed_date": None,
        "days_until": None,
        "source": "synthetic",
        "ingest_run_id": "test",
        "fetched_at": datetime.now(timezone.utc),
    }
    base.update(overrides)
    return base


class TestEasterDate:
    def test_known_dates(self):
        assert easter_date(2024) == date(2024, 3, 31)
        assert easter_date(2025) == date(2025, 4, 20)
        assert easter_date(2026) == date(2026, 4, 5)
        assert easter_date(2027) == date(2027, 3, 28)
        assert easter_date(2000) == date(2000, 4, 23)

    @pytest.mark.parametrize("year", range(1900, 2100, 7))
    def test_easter_always_in_march_or_april(self, year):
        assert easter_date(year).month in (3, 4)


class TestConstants:
    def test_output_columns_count_is_13(self):
        assert len(HOLIDAY_OUTPUT_COLUMNS) == 13

    def test_valid_states(self):
        assert "NSW" in VALID_STATES
        assert "WA" in VALID_STATES

    def test_valid_holiday_types(self):
        assert {"national", "state", "regional", "observance"} <= VALID_HOLIDAY_TYPES


class TestSyntheticStub:
    def test_returns_holidays_for_all_six_regions(self):
        docs = synthetic_stub(NEM_REGIONS, 2026)
        assert {d["region"] for d in docs} == set(NEM_REGIONS)

    def test_includes_national_holidays(self):
        docs = synthetic_stub(NEM_REGIONS, 2026)
        names = {d["holiday_name"] for d in docs}
        for must_have in (
            "New Year's Day",
            "Australia Day",
            "Anzac Day",
            "Christmas Day",
            "Boxing Day",
        ):
            assert must_have in names

    def test_includes_state_specific_holidays(self):
        docs = synthetic_stub(NEM_REGIONS, 2026)
        vic_names = {d["holiday_name"] for d in docs if d["region"] == "VIC1"}
        assert "Melbourne Cup Day" in vic_names
        wa_names = {d["holiday_name"] for d in docs if d["region"] == "WEM"}
        assert "Western Australia Day" in wa_names

    def test_easter_dates_present(self):
        docs = synthetic_stub(NEM_REGIONS, 2026)
        easter_docs = [d for d in docs if d["holiday_name"] == "Easter Sunday"]
        assert len(easter_docs) > 0
        assert easter_docs[0]["date"] == "2026-04-05"

    def test_good_friday_two_days_before_easter(self):
        docs = synthetic_stub(NEM_REGIONS, 2026)
        gf = [d for d in docs if d["holiday_name"] == "Good Friday"]
        assert gf[0]["date"] == "2026-04-03"

    def test_christmas_and_boxing_day_separate(self):
        docs = synthetic_stub(NEM_REGIONS, 2026)
        xmas = [d for d in docs if d["holiday_name"] == "Christmas Day"]
        boxing = [d for d in docs if d["holiday_name"] == "Boxing Day"]
        assert xmas[0]["date"] == "2026-12-25"
        assert boxing[0]["date"] == "2026-12-26"

    def test_observed_rollover_for_weekend_christmas(self):
        """2027-12-25 (Christmas) is a Saturday -> observed Monday
        in NSW, VIC, SA, WA."""
        docs = synthetic_stub(NEM_REGIONS, 2027)
        observed = [d for d in docs if d.get("is_observed") is True]
        assert len(observed) > 0
        christmas_observed = [o for o in observed if "Christmas" in o["holiday_name"]]
        assert christmas_observed
        assert christmas_observed[0]["date"] == "2027-12-27"

    def test_no_observed_rollover_for_weekday(self):
        """2025-12-25 is a Thursday. No Monday observed date needed."""
        docs = synthetic_stub(NEM_REGIONS, 2025)
        observed = [d for d in docs if d.get("is_observed") is True]
        assert not any("Christmas" in o["holiday_name"] for o in observed)

    def test_respects_region_subset(self):
        docs = synthetic_stub(("NSW1",), 2026)
        assert {d["region"] for d in docs} == {"NSW1"}


class TestApplyDataQualityFixes:
    def test_nan_becomes_none(self):
        doc = _make_doc(days_until=float("nan"))
        result = apply_data_quality_fixes([doc], 2026, NEM_REGIONS)
        assert result[0]["days_until"] is None

    def test_invalid_region_dropped(self):
        doc = _make_doc(region="INVALID")
        result = apply_data_quality_fixes([doc], 2026, NEM_REGIONS)
        assert len(result) == 0

    def test_bad_date_dropped(self):
        doc = _make_doc(date="not-a-date")
        result = apply_data_quality_fixes([doc], 2026, NEM_REGIONS)
        assert len(result) == 0

    def test_year_filter(self):
        doc = _make_doc(date="2025-12-25")
        result = apply_data_quality_fixes([doc], 2026, NEM_REGIONS)
        assert len(result) == 0

    def test_invalid_holiday_type_normalized(self):
        doc = _make_doc(holiday_type="made_up")
        result = apply_data_quality_fixes([doc], 2026, NEM_REGIONS)
        assert result[0]["holiday_type"] == "state"

    def test_dedupe_same_region_date(self):
        doc1 = _make_doc(holiday_name="Christmas")
        doc2 = _make_doc(holiday_name="Boxing Day")  # same region+date
        result = apply_data_quality_fixes([doc1, doc2], 2026, NEM_REGIONS)
        assert len(result) == 1
        assert result[0]["holiday_name"] == "Boxing Day"

    def test_all_columns_present(self):
        docs = synthetic_stub(NEM_REGIONS, 2026)
        cleaned = apply_data_quality_fixes(docs, 2026, NEM_REGIONS)
        for col in HOLIDAY_OUTPUT_COLUMNS:
            assert col in cleaned[0]


class TestAttachDaysUntil:
    def test_days_until_set_correctly(self):
        doc = _make_doc(date="2026-12-25")
        attach_days_until([doc], date(2026, 1, 1))
        assert doc["days_until"] == 358

    def test_days_until_negative_for_past(self):
        doc = _make_doc(date="2026-01-01")
        attach_days_until([doc], date(2026, 6, 1))
        assert doc["days_until"] == -151
