"""Unit tests for ecolens.ingestion.sources.aemo_nem.transformers."""

from __future__ import annotations

import pandas as pd
import pytest

from ecolens.ingestion.sources.aemo_nem.transformers import (
    aggregate_duids_to_fueltechs,
    aggregate_to_network,
    apply_data_quality_fixes,
    apply_fuel_map,
    build_day_frame,
    compute_derived,
    diagnose,
    extract_regionsum,
)

DUID_MAP = {"BAYSW1": "coal_black", "WELLS1": "wind", "HRONBNK": "battery"}


def _dunit_rows(**overrides) -> pd.DataFrame:
    row = {
        "SETTLEMENTDATE": "2026/07/19 04:05:00",
        "RUNNO": "1",
        "DUID": "BAYSW1",
        "INTERVENTION": "0",
        "TOTALCLEARED": "200.0",
    }
    row.update(overrides)
    return pd.DataFrame([row])


class TestAggregateDuidsToFueltechs:
    def test_maps_duid_to_fueltech_and_aggregates_to_network_level(self):
        wide = aggregate_duids_to_fueltechs(_dunit_rows(), DUID_MAP)
        assert wide.iloc[0]["region"] == "NEM"
        assert wide.iloc[0]["coal_black"] == 200.0

    def test_filters_out_intervention_pricing_runs(self):
        """Regression: PUBLIC_DAILY carries a duplicate row per DUID for
        AEMO's intervention pricing pass — without filtering to
        INTERVENTION=='0', generation is silently double-counted."""
        df = pd.concat(
            [_dunit_rows(), _dunit_rows(INTERVENTION="1", TOTALCLEARED="999.0")],
            ignore_index=True,
        )
        wide = aggregate_duids_to_fueltechs(df, DUID_MAP)
        assert wide.iloc[0]["coal_black"] == 200.0  # not 200 + 999

    def test_unmapped_duid_falls_through_to_unknown(self):
        df = _dunit_rows(DUID="SOME_NEW_DUID")
        wide = aggregate_duids_to_fueltechs(df, DUID_MAP)
        assert "unknown" in wide.columns

    def test_battery_negative_totalcleared_becomes_charge(self):
        df = _dunit_rows(DUID="HRONBNK", TOTALCLEARED="-50.0")
        wide = aggregate_duids_to_fueltechs(df, DUID_MAP)
        assert wide.iloc[0]["battery_charge_mw"] == 50.0
        assert wide.iloc[0].get("battery", 0.0) == 0.0

    def test_empty_input_returns_empty_frame(self):
        wide = aggregate_duids_to_fueltechs(pd.DataFrame(), DUID_MAP)
        assert wide.empty


class TestExtractRegionsum:
    def _dregion_row(self, **overrides) -> pd.DataFrame:
        row = {
            "SETTLEMENTDATE": "2026/07/19 04:05:00",
            "INTERVENTION": "0",
            "REGIONID": "NSW1",
            "TOTALDEMAND": "7000.0",
            "RRP": "85.5",
            "NETINTERCHANGE": "-500.0",
        }
        row.update(overrides)
        return pd.DataFrame([row])

    def test_extracts_demand_price_and_splits_net_interchange(self):
        out = extract_regionsum(self._dregion_row())
        row = out.iloc[0]
        assert row["demand_mw"] == 7000.0
        assert row["price_mwh"] == 85.5
        assert row["net_import_mw"] == -500.0
        # negative net interchange = net export
        assert row["interconnector_imports_mw"] == 0.0
        assert row["interconnector_exports_mw"] == 500.0

    def test_positive_net_interchange_is_import(self):
        out = extract_regionsum(self._dregion_row(NETINTERCHANGE="300.0"))
        row = out.iloc[0]
        assert row["interconnector_imports_mw"] == 300.0
        assert row["interconnector_exports_mw"] == 0.0

    def test_filters_intervention_runs(self):
        df = pd.concat(
            [
                self._dregion_row(),
                self._dregion_row(INTERVENTION="1", TOTALDEMAND="99999"),
            ],
            ignore_index=True,
        )
        out = extract_regionsum(df)
        assert len(out) == 1
        assert out.iloc[0]["demand_mw"] == 7000.0

    def test_empty_input(self):
        out = extract_regionsum(pd.DataFrame())
        assert out.empty


class TestApplyFuelMapAndComputeDerived:
    def test_renewable_proportion_on_0_to_100_scale(self):
        wide = pd.DataFrame([{"ts": "t1", "coal_black": 100.0, "wind": 100.0}])
        wide = apply_fuel_map(wide)
        wide = compute_derived(wide)
        row = wide.iloc[0]
        assert row["renewable_proportion"] == pytest.approx(50.0)
        assert row["network_code"] == "NEM"
        assert row["source"] == "aemo_nem"
        assert row["data_quality_status"] == "final"

    def test_total_generation_excludes_battery_charge(self):
        wide = pd.DataFrame(
            [{"ts": "t1", "coal_black": 100.0, "battery_charge_mw": 10.0}]
        )
        wide = apply_fuel_map(wide)
        wide = compute_derived(wide)
        assert wide.iloc[0]["total_generation_mw"] == 90.0

    def test_empty_frame_is_noop(self):
        assert apply_fuel_map(pd.DataFrame()).empty
        assert compute_derived(pd.DataFrame()).empty

    def test_total_generation_is_none_when_no_generation_columns_present(self):
        wide = pd.DataFrame([{"ts": "t1", "region": "NSW1", "demand_mw": 7000.0}])
        wide = compute_derived(wide)
        assert wide.iloc[0]["total_generation_mw"] is None


class TestAggregateToNetwork:
    def test_rolls_up_per_region_rows_and_zeroes_interconnectors(self):
        wide = pd.DataFrame(
            [
                {
                    "ts": "t1",
                    "region": "NSW1",
                    "demand_mw": 100.0,
                    "coal_black_mw": 50.0,
                },
                {
                    "ts": "t1",
                    "region": "QLD1",
                    "demand_mw": 200.0,
                    "coal_black_mw": 30.0,
                },
            ]
        )
        grouped = aggregate_to_network(wide)
        assert len(grouped) == 1
        row = grouped.iloc[0]
        assert row["region"] == "NEM"
        assert row["demand_mw"] == 300.0
        assert row["coal_black_mw"] == 80.0
        assert row["interconnector_imports_mw"] == 0

    def test_noop_on_empty_or_missing_region(self):
        assert aggregate_to_network(pd.DataFrame()).empty


class TestApplyDataQualityFixes:
    def test_nan_becomes_none(self):
        docs = [{"demand_mw": float("nan")}]
        cleaned = apply_data_quality_fixes(docs)
        assert cleaned[0]["demand_mw"] is None

    def test_emissions_intensity_scaled_down_when_large(self):
        docs = [{"emissions_intensity_kgco2e_per_mwh": 850.0}]
        cleaned = apply_data_quality_fixes(docs)
        assert cleaned[0]["emissions_intensity_kgco2e_per_mwh"] == 0.85

    def test_network_level_row_zeroes_interconnectors(self):
        docs = [
            {
                "region": "NEM",
                "network_code": "NEM",
                "interconnector_imports_mw": 123,
                "interconnector_exports_mw": 456,
                "net_import_mw": -333,
            }
        ]
        cleaned = apply_data_quality_fixes(docs)
        assert cleaned[0]["interconnector_imports_mw"] == 0
        assert cleaned[0]["interconnector_exports_mw"] == 0
        assert cleaned[0]["net_import_mw"] == 0

    def test_negative_generation_clipped_to_zero(self):
        docs = [{"wind_mw": -5.0}]
        cleaned = apply_data_quality_fixes(docs)
        assert cleaned[0]["wind_mw"] == 0


class TestDiagnose:
    def test_runs_without_error(self):
        diagnose([])
        diagnose([{"coal_black_mw": 0.0}, {"coal_black_mw": 0.0}])


class TestBuildDayFrame:
    def test_combines_network_level_and_per_region_rows(self):
        tables = {
            "DUNIT": _dunit_rows(),
            "DREGION": pd.DataFrame(
                [
                    {
                        "SETTLEMENTDATE": "2026/07/19 04:05:00",
                        "INTERVENTION": "0",
                        "REGIONID": "NSW1",
                        "TOTALDEMAND": "7000.0",
                        "RRP": "85.5",
                        "NETINTERCHANGE": "0.0",
                    }
                ]
            ),
        }
        result = build_day_frame(tables, DUID_MAP)
        regions = set(result["region"])
        assert regions == {"NEM", "NSW1"}
        nem_row = result[result["region"] == "NEM"].iloc[0]
        assert nem_row["coal_black_mw"] == 200.0
        nsw_row = result[result["region"] == "NSW1"].iloc[0]
        assert nsw_row["demand_mw"] == 7000.0
