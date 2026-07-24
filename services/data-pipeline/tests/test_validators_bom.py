"""Tests for ecolens.ingestion.validators.bom."""

from __future__ import annotations

import pandas as pd
import pandera.errors
import pytest

from ecolens.ingestion.validators.bom import validate


def _valid_doc(**overrides) -> dict:
    doc = {
        "ts": pd.Timestamp("2026-07-20T10:00:00Z"),
        "region": "NSW1",
        "station_id": "066037",
        "temp_c": 22.0,
        "humidity_pct": 50.0,
        "source": "bom",
        "wind_speed_kmh": 10.0,  # extra column, allowed (strict=False)
    }
    doc.update(overrides)
    return doc


class TestValidate:
    def test_empty_list_returns_unchanged(self):
        assert validate([]) == []

    def test_valid_doc_passes_through(self):
        result = validate([_valid_doc()])
        assert result[0]["region"] == "NSW1"
        assert result[0]["wind_speed_kmh"] == 10.0

    def test_invalid_region_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(region="BOGUS")])

    def test_wrong_source_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(source="not_bom")])

    def test_temp_out_of_bounds_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(temp_c=99.0)])

    def test_humidity_out_of_bounds_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(humidity_pct=150.0)])

    def test_duplicate_station_id_and_ts_raises(self):
        docs = [_valid_doc(), _valid_doc()]
        with pytest.raises(pandera.errors.SchemaError):
            validate(docs)

    def test_wem_region_is_valid(self):
        result = validate([_valid_doc(region="WEM", station_id="009225")])
        assert result[0]["region"] == "WEM"

    def test_open_meteo_era5_source_is_valid(self):
        result = validate([_valid_doc(source="open_meteo_era5")])
        assert result[0]["source"] == "open_meteo_era5"
