"""Tests for ecolens.ingestion.validators.holidays."""

from __future__ import annotations

import pandera.errors
import pytest

from ecolens.ingestion.validators.holidays import validate


def _valid_doc(**overrides) -> dict:
    doc = {
        "date": "2026-01-01",
        "region": "NSW1",
        "state": "NSW",
        "holiday_name": "New Year's Day",
        "holiday_type": "national",
        "source": "synthetic",
        "is_business_day": False,  # extra column, allowed (strict=False)
    }
    doc.update(overrides)
    return doc


class TestValidate:
    def test_empty_list_returns_unchanged(self):
        assert validate([]) == []

    def test_valid_doc_passes_through(self):
        result = validate([_valid_doc()])
        assert result[0]["region"] == "NSW1"
        assert result[0]["is_business_day"] == False  # noqa: E712

    def test_invalid_region_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(region="BOGUS")])

    def test_invalid_state_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(state="BOGUS")])

    def test_invalid_holiday_type_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(holiday_type="made_up")])

    def test_duplicate_region_and_date_raises(self):
        docs = [_valid_doc(), _valid_doc(holiday_name="Other Day")]
        with pytest.raises(pandera.errors.SchemaError):
            validate(docs)

    def test_wem_region_is_valid(self):
        result = validate([_valid_doc(region="WEM", state="WA", holiday_name="WA Day")])
        assert result[0]["region"] == "WEM"
