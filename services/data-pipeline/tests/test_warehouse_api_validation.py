"""Tests for ecolens.warehouse.api.validation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from ecolens.warehouse.api.settings import WarehouseApiSettings
from ecolens.warehouse.api.validation import (
    validate_range,
    validate_region,
    validate_year,
)


class TestValidateRegion:
    def test_valid_region_passes(self):
        validate_region("NSW1", WarehouseApiSettings())

    def test_invalid_region_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_region("BOGUS", WarehouseApiSettings())
        assert exc_info.value.status_code == 400


class TestValidateRange:
    def test_valid_range_passes(self):
        now = datetime.now(timezone.utc)
        validate_range(now - timedelta(hours=1), now)

    def test_inverted_range_raises_400(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(HTTPException) as exc_info:
            validate_range(now, now - timedelta(hours=1))
        assert exc_info.value.status_code == 400

    def test_equal_bounds_raises_400(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(HTTPException):
            validate_range(now, now)

    def test_range_over_one_year_raises_400(self):
        now = datetime.now(timezone.utc)
        with pytest.raises(HTTPException) as exc_info:
            validate_range(now, now + timedelta(days=400))
        assert exc_info.value.status_code == 400


class TestValidateYear:
    def test_valid_year_passes(self):
        validate_year(2026)

    @pytest.mark.parametrize("year", [1999, 2101])
    def test_out_of_range_year_raises_400(self, year):
        with pytest.raises(HTTPException) as exc_info:
            validate_year(year)
        assert exc_info.value.status_code == 400
