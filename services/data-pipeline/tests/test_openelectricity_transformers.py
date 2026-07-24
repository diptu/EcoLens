"""Unit tests for ecolens.ingestion.sources.openelectricity.transformers.

Pure pandas logic, no network I/O — synthetic per-metric DataFrames in,
canonical rows out.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ecolens.ingestion.sources.openelectricity.transformers import (
    diagnose_data_quality,
    merge_network,
    migrate_v0_to_v1,
    minimal_doc,
    normalize_data_quality,
)


class TestNormalizeDataQuality:
    def test_known_tiers_map_to_canonical(self):
        assert normalize_data_quality("dispatch") == "realtime"
        assert normalize_data_quality("FINAL") == "final"
        assert normalize_data_quality("  scheduled  ") == "forecast"
        assert normalize_data_quality("revised-2") == "revised"

    def test_none_or_empty_is_unknown(self):
        assert normalize_data_quality(None) == "unknown"
        assert normalize_data_quality("") == "unknown"

    def test_unrecognized_value_is_unknown(self):
        assert normalize_data_quality("some-made-up-tier") == "unknown"


def _power_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ts": "2026-07-20T10:00:00+10:00",
                "region": "NEM",
                "fuel": "wind",
                "mw": 100.0,
            },
            {
                "ts": "2026-07-20T10:00:00+10:00",
                "region": "NEM",
                "fuel": "coal_black",
                "mw": 200.0,
            },
            {
                "ts": "2026-07-20T10:00:00+10:00",
                "region": "NEM",
                "fuel": "bioenergy_biogas",
                "mw": 5.0,
            },
            {
                "ts": "2026-07-20T10:00:00+10:00",
                "region": "NEM",
                "fuel": "bioenergy_biomass",
                "mw": 3.0,
            },
        ]
    )


class TestMergeNetwork:
    def test_basic_merge_maps_fuels_and_aggregates_biomass(self):
        frames = {"power": _power_frame()}
        result = merge_network("NEM", frames, since=None)

        assert result is not None
        assert len(result) == 1
        row = result.iloc[0]
        assert row["wind_mw"] == 100.0
        assert row["coal_black_mw"] == 200.0
        # bioenergy_biogas + bioenergy_biomass both map to biomass_mw and sum
        assert row["biomass_mw"] == 8.0
        assert row["network_code"] == "NEM"
        assert row["source"] == "openelectricity"
        assert row["schema_version"] == "1.0"

    def test_total_generation_excludes_battery_charge(self):
        power = pd.concat(
            [
                _power_frame(),
                pd.DataFrame(
                    [
                        {
                            "ts": "2026-07-20T10:00:00+10:00",
                            "region": "NEM",
                            "fuel": "battery_discharging",
                            "mw": 10.0,
                        },
                        {
                            "ts": "2026-07-20T10:00:00+10:00",
                            "region": "NEM",
                            "fuel": "battery_charging",
                            "mw": 4.0,
                        },
                    ]
                ),
            ],
            ignore_index=True,
        )
        result = merge_network("NEM", {"power": power}, since=None)
        row = result.iloc[0]
        # GENERATION_COLUMNS includes battery_discharge_mw but not
        # battery_charge_mw (a load) — sum(wind+coal_black+biomass+
        # battery_discharge) = 318, then battery_charge (4) is
        # subtracted explicitly.
        assert row["total_generation_mw"] == pytest.approx(314.0)
        assert row["battery_charge_mw"] == 4.0

    def test_renewable_proportion_computed_on_0_to_100_scale(self):
        # wind(100) + biomass(8) renewable out of wind+coal+biomass = 308 total
        result = merge_network("NEM", {"power": _power_frame()}, since=None)
        row = result.iloc[0]
        expected = (100.0 + 8.0) / 308.0 * 100
        assert row["renewable_proportion"] == pytest.approx(expected)

    def test_market_value_computed_from_price_and_demand_when_absent(self):
        price = pd.DataFrame(
            [{"ts": "2026-07-20T10:00:00+10:00", "region": "NEM", "price_mwh": 100.0}]
        )
        demand = pd.DataFrame(
            [{"ts": "2026-07-20T10:00:00+10:00", "region": "NEM", "demand_mw": 6000.0}]
        )
        result = merge_network(
            "NEM",
            {"power": _power_frame(), "price": price, "demand": demand},
            since=None,
        )
        row = result.iloc[0]
        # market_value = price * demand * (5/60)
        assert row["market_value"] == pytest.approx(100.0 * 6000.0 * (5.0 / 60.0))

    def test_net_import_mw_zero_when_no_interconnector_data(self):
        """Regression: wide.get(col, 0).fillna(0) used to crash with
        AttributeError ('int' has no .fillna) when the column never
        got joined in at all — e.g. WEM genuinely has no flow data."""
        result = merge_network("NEM", {"power": _power_frame()}, since=None)
        row = result.iloc[0]
        # net_import_mw is explicitly zero-filled via _col_or_zero;
        # interconnector_imports_mw/exports_mw themselves are left
        # null (no data reported) rather than defaulted to 0.
        assert row["net_import_mw"] == 0.0
        assert pd.isna(row["interconnector_imports_mw"])

    def test_net_import_mw_is_imports_minus_exports(self):
        imports = pd.DataFrame(
            [{"ts": "2026-07-20T10:00:00+10:00", "region": "NEM", "flow_mw": 500.0}]
        )
        exports = pd.DataFrame(
            [{"ts": "2026-07-20T10:00:00+10:00", "region": "NEM", "flow_mw": 200.0}]
        )
        result = merge_network(
            "NEM",
            {
                "power": _power_frame(),
                "interconnector_imports": imports,
                "interconnector_exports": exports,
            },
            since=None,
        )
        row = result.iloc[0]
        assert row["interconnector_imports_mw"] == 500.0
        assert row["interconnector_exports_mw"] == 200.0
        assert row["net_import_mw"] == 300.0

    def test_output_has_all_34_canonical_columns(self):
        from ecolens.ingestion.sources.openelectricity.schema import OUTPUT_COLUMNS

        result = merge_network("NEM", {"power": _power_frame()}, since=None)
        assert list(result.columns) == OUTPUT_COLUMNS

    def test_unmapped_fuel_is_dropped_not_crashed(self):
        power = pd.concat(
            [
                _power_frame(),
                pd.DataFrame(
                    [
                        {
                            "ts": "2026-07-20T10:00:00+10:00",
                            "region": "NEM",
                            "fuel": "some_new_fueltech_v2",
                            "mw": 999.0,
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )
        result = merge_network("NEM", {"power": power}, since=None)
        # Doesn't crash, and the unmapped fuel isn't silently folded
        # into a canonical column.
        assert "some_new_fueltech_v2" not in result.columns
        assert result.iloc[0]["wind_mw"] == 100.0

    def test_falls_back_to_minimal_doc_when_power_missing(self):
        price = pd.DataFrame(
            [{"ts": "2026-07-20T10:00:00+10:00", "region": "NEM", "price_mwh": 85.0}]
        )
        result = merge_network("NEM", {"price": price}, since=None)
        assert result is not None
        assert result.iloc[0]["price_mwh"] == 85.0
        assert result.iloc[0]["total_generation_mw"] is None

    def test_default_data_quality_status_is_realtime(self):
        result = merge_network("NEM", {"power": _power_frame()}, since=None)
        assert result.iloc[0]["data_quality_status"] == "realtime"


class TestMinimalDoc:
    def test_returns_none_when_nothing_present(self):
        assert minimal_doc({}, "NEM", since=None) is None

    def test_combines_available_scalar_metrics(self):
        price = pd.DataFrame(
            [{"ts": "2026-07-20T10:00:00+10:00", "region": "NEM", "price_mwh": 85.0}]
        )
        demand = pd.DataFrame(
            [{"ts": "2026-07-20T10:00:00+10:00", "region": "NEM", "demand_mw": 5000.0}]
        )
        result = minimal_doc({"price": price, "demand": demand}, "NEM", since=None)
        assert result is not None
        row = result.iloc[0]
        assert row["price_mwh"] == 85.0
        assert row["demand_mw"] == 5000.0
        assert row["network_code"] == "NEM"
        assert row["data_quality_status"] == "realtime"


class TestDiagnoseDataQuality:
    def test_runs_without_error_on_empty_frame(self):
        diagnose_data_quality(pd.DataFrame())

    def test_runs_without_error_on_normal_frame(self):
        result = merge_network("NEM", {"power": _power_frame()}, since=None)
        diagnose_data_quality(result)


class TestMigrateV0ToV1:
    def test_noop_if_already_v1(self):
        doc = {"schema_version": "1.0", "coal_mw": 100}
        assert migrate_v0_to_v1(doc) == doc

    def test_splits_coal_mw_using_v0_buggy_fetcher_leftovers(self):
        doc = {"coal_mw": 300, "coal_black": 200, "coal_brown": 100}
        migrated = migrate_v0_to_v1(doc)
        assert migrated["coal_black_mw"] == 200
        assert migrated["coal_brown_mw"] == 100
        assert "coal_mw" not in migrated
        assert migrated["schema_version"] == "1.0"

    def test_splits_gas_mw_and_aggregates_minor_types(self):
        doc = {
            "gas_mw": 500,
            "gas_ccgt": 200,
            "gas_ocgt": 100,
            "gas_recip": 50,
            "gas_steam": 30,
            "gas_wcmg": 20,
        }
        migrated = migrate_v0_to_v1(doc)
        assert migrated["gas_ccgt_mw"] == 200
        assert migrated["gas_ocgt_mw"] == 100
        assert migrated["gas_other_mw"] == 100  # 50 + 30 + 20
        assert "gas_mw" not in migrated
        assert "gas_recip" not in migrated

    def test_renames_status_to_data_quality_status(self):
        doc = {"status": "dispatch"}
        migrated = migrate_v0_to_v1(doc)
        assert migrated["data_quality_status"] == "realtime"
        assert "status" not in migrated

    def test_renames_flow_columns(self):
        doc = {"flow_imports_mw": 10, "flow_exports_mw": 5}
        migrated = migrate_v0_to_v1(doc)
        assert migrated["interconnector_imports_mw"] == 10
        assert migrated["interconnector_exports_mw"] == 5

    def test_drops_total_curtailment(self):
        doc = {"curtailment_mw": 42}
        migrated = migrate_v0_to_v1(doc)
        assert "curtailment_mw" not in migrated
        assert migrated["schema_version"] == "1.0"
