"""Tests for ecolens.ingestion.validators.openelectricity."""

from __future__ import annotations

import pandera.errors
import pytest

from ecolens.ingestion.validators.openelectricity import validate


def _valid_doc(**overrides) -> dict:
    doc = {
        "ts": "2026-07-20T10:00:00+10:00",
        "network_code": "NEM",
        "region": "NEM",
        "total_generation_mw": 25000.0,
        "source": "openelectricity",
        "wind_mw": 100.0,  # extra column, allowed (strict=False)
    }
    doc.update(overrides)
    return doc


class TestValidate:
    def test_empty_list_returns_unchanged(self):
        assert validate([]) == []

    def test_valid_doc_passes_through(self):
        docs = [_valid_doc()]
        result = validate(docs)
        assert result[0]["network_code"] == "NEM"
        assert result[0]["wind_mw"] == 100.0

    def test_invalid_network_code_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(network_code="BOGUS")])

    def test_wrong_source_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(source="not_openelectricity")])

    def test_null_total_generation_raises(self):
        with pytest.raises(pandera.errors.SchemaError):
            validate([_valid_doc(total_generation_mw=None)])

    def test_duplicate_network_code_and_ts_raises(self):
        docs = [_valid_doc(), _valid_doc()]  # same network_code + ts twice
        with pytest.raises(pandera.errors.SchemaError):
            validate(docs)

    def test_wem_network_code_is_valid(self):
        result = validate([_valid_doc(network_code="WEM", region="WEM")])
        assert result[0]["network_code"] == "WEM"
