"""Tests for ecolens_forecast_api.validation."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from ecolens_forecast_api.settings import ForecastApiSettings
from ecolens_forecast_api.validation import validate_horizon, validate_region

SETTINGS = ForecastApiSettings()


class TestValidateRegion:
    def test_valid_region_does_not_raise(self):
        validate_region("NSW1", SETTINGS)

    def test_invalid_region_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_region("BOGUS", SETTINGS)
        assert exc_info.value.status_code == 400


class TestValidateHorizon:
    def test_valid_horizon_does_not_raise(self):
        validate_horizon(48, SETTINGS)
        validate_horizon(1, SETTINGS)

    def test_zero_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_horizon(0, SETTINGS)
        assert exc_info.value.status_code == 400

    def test_over_max_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_horizon(49, SETTINGS)
        assert exc_info.value.status_code == 400
