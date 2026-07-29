"""Tests for ecolens.warehouse.core.regions."""

from __future__ import annotations

import pytest

from ecolens.warehouse.core.regions import (
    ANALYTICS_VALID_REGIONS,
    NEM_SUB_REGIONS,
    resolve_region_group,
)


class TestResolveRegionGroup:
    def test_nem_expands_to_five_sub_regions(self):
        assert resolve_region_group("NEM") == NEM_SUB_REGIONS
        assert "WEM" not in resolve_region_group("NEM")

    def test_wem_is_a_single_region_group(self):
        assert resolve_region_group("WEM") == ("WEM",)

    def test_a_concrete_nem_sub_region_is_a_single_region_group(self):
        assert resolve_region_group("NSW1") == ("NSW1",)

    def test_every_valid_region_resolves_without_error(self):
        for region in ANALYTICS_VALID_REGIONS:
            assert resolve_region_group(region)

    def test_unknown_region_raises(self):
        with pytest.raises(ValueError):
            resolve_region_group("BOGUS")
