"""Unit tests for ecolens.ingestion.sources.aemo_wem.transformers."""

from __future__ import annotations

import pandas as pd
import pytest

from ecolens.ingestion.sources.aemo_wem.transformers import (
    aggregate_facilities_to_fueltechs,
    apply_data_quality_fixes,
    apply_fuel_map,
    build_day_frame,
    compute_derived,
    diagnose,
    extract_demand,
    extract_price,
)

FACILITY_MAP = {
    "BW1_BLUEWATERS_G2": "coal_black",
    "ALBANY_WF1": "wind",
    "COLLIE_ESR1": "battery",
}


class TestAggregateFacilitiesToFueltechs:
    def test_scales_mwh_per_5min_interval_to_average_mw(self):
        """Regression: WEM's `quantity` is 5-min interval ENERGY in
        MWh, not instantaneous MW — confirmed live (Bluewaters G2's
        217 MW nameplate unit reports ~17.9 MWh/interval, which x12
        gives ~215 MW). Left unscaled, every generation figure is
        silently ~12x too low."""
        rows = [
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "code": "BW1_BLUEWATERS_G2",
                "quantity": 17.9416676,
            }
        ]
        wide = aggregate_facilities_to_fueltechs(rows, FACILITY_MAP)
        assert wide.iloc[0]["coal_black"] == pytest.approx(17.9416676 * 12)

    def test_maps_facility_code_to_fueltech(self):
        rows = [
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "code": "ALBANY_WF1",
                "quantity": 0.35,
            }
        ]
        wide = aggregate_facilities_to_fueltechs(rows, FACILITY_MAP)
        assert "wind" in wide.columns
        assert wide.iloc[0]["wind"] == pytest.approx(0.35 * 12)

    def test_unmapped_facility_falls_through_to_unknown(self):
        rows = [
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "code": "SOME_NEW_FACILITY",
                "quantity": 1.0,
            }
        ]
        wide = aggregate_facilities_to_fueltechs(rows, FACILITY_MAP)
        assert "unknown" in wide.columns

    def test_battery_negative_quantity_becomes_charge(self):
        rows = [
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "code": "COLLIE_ESR1",
                "quantity": -1.0,
            }
        ]
        wide = aggregate_facilities_to_fueltechs(rows, FACILITY_MAP)
        assert wide.iloc[0]["battery_charge_mw"] == pytest.approx(12.0)

    def test_duplicate_rows_deduped_by_code_and_interval(self):
        rows = [
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "code": "BW1_BLUEWATERS_G2",
                "quantity": 10.0,
            },
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "code": "BW1_BLUEWATERS_G2",
                "quantity": 10.0,
            },
        ]
        wide = aggregate_facilities_to_fueltechs(rows, FACILITY_MAP)
        assert wide.iloc[0]["coal_black"] == pytest.approx(10.0 * 12)

    def test_empty_input(self):
        assert aggregate_facilities_to_fueltechs([], FACILITY_MAP).empty


class TestExtractDemandAndPrice:
    def test_extract_demand(self):
        rows = [
            {
                "dispatchInterval": "2026-07-19T08:00:00+08:00",
                "operationalDemand": 2326.5,
                "operationalWithdrawal": -222.5,
            }
        ]
        out = extract_demand(rows)
        assert out.iloc[0]["demand_mw"] == 2326.5

    def test_extract_price(self):
        rows = [
            {
                "tradingInterval": "2026-07-19T08:00:00+08:00",
                "referenceTradingPrice": 137.64,
                "isPublished": True,
            }
        ]
        out = extract_price(rows)
        assert out.iloc[0]["price_mwh"] == 137.64

    def test_both_empty_inputs(self):
        assert extract_demand([]).empty
        assert extract_price([]).empty


class TestApplyFuelMapAndComputeDerived:
    def test_renewable_proportion_on_0_to_100_scale(self):
        wide = pd.DataFrame([{"ts": "t1", "coal_black": 100.0, "wind": 100.0}])
        wide = apply_fuel_map(wide)
        wide = compute_derived(wide)
        row = wide.iloc[0]
        assert row["renewable_proportion"] == pytest.approx(50.0)
        assert row["network_code"] == "WEM"
        assert row["region"] == "WEM"
        assert row["source"] == "aemo_wem"

    def test_interconnectors_always_zero_islanded(self):
        wide = pd.DataFrame([{"ts": "t1", "coal_black": 100.0}])
        wide = apply_fuel_map(wide)
        wide = compute_derived(wide)
        row = wide.iloc[0]
        assert row["interconnector_imports_mw"] == 0
        assert row["interconnector_exports_mw"] == 0
        assert row["net_import_mw"] == 0

    def test_empty_frame_is_noop(self):
        assert apply_fuel_map(pd.DataFrame()).empty
        assert compute_derived(pd.DataFrame()).empty


class TestApplyDataQualityFixes:
    def test_nan_becomes_none(self):
        cleaned = apply_data_quality_fixes([{"demand_mw": float("nan")}])
        assert cleaned[0]["demand_mw"] is None

    def test_negative_generation_clipped(self):
        cleaned = apply_data_quality_fixes([{"wind_mw": -1.0}])
        assert cleaned[0]["wind_mw"] == 0

    def test_emissions_scaled(self):
        cleaned = apply_data_quality_fixes(
            [{"emissions_intensity_kgco2e_per_mwh": 900.0}]
        )
        assert cleaned[0]["emissions_intensity_kgco2e_per_mwh"] == 0.9


class TestDiagnose:
    def test_runs_without_error(self):
        diagnose([])
        diagnose([{"coal_black_mw": 0.0}])


class TestBuildDayFrame:
    def test_merges_scada_demand_and_price_by_ts(self):
        raw = {
            "scada": [
                {
                    "dispatchInterval": "2026-07-19T08:00:00+08:00",
                    "code": "BW1_BLUEWATERS_G2",
                    "quantity": 17.94,
                },
            ],
            "demand": [
                {
                    "dispatchInterval": "2026-07-19T08:00:00+08:00",
                    "operationalDemand": 2326.5,
                    "operationalWithdrawal": 0,
                },
            ],
            "price": [
                {
                    "tradingInterval": "2026-07-19T08:00:00+08:00",
                    "referenceTradingPrice": 137.64,
                    "isPublished": True,
                },
            ],
        }
        result = build_day_frame(raw, FACILITY_MAP)
        assert len(result) == 1
        row = result.iloc[0]
        assert row["coal_black_mw"] == pytest.approx(17.94 * 12)
        assert row["demand_mw"] == 2326.5
        assert row["price_mwh"] == 137.64
        assert row["region"] == "WEM"

    def test_price_on_30min_grid_leaves_5min_rows_null(self):
        raw = {
            "scada": [
                {
                    "dispatchInterval": "2026-07-19T08:00:00+08:00",
                    "code": "BW1_BLUEWATERS_G2",
                    "quantity": 10.0,
                },
                {
                    "dispatchInterval": "2026-07-19T08:05:00+08:00",
                    "code": "BW1_BLUEWATERS_G2",
                    "quantity": 10.0,
                },
            ],
            "demand": [],
            "price": [
                {
                    "tradingInterval": "2026-07-19T08:00:00+08:00",
                    "referenceTradingPrice": 100.0,
                    "isPublished": True,
                },
            ],
        }
        result = build_day_frame(raw, FACILITY_MAP)
        row_0800 = result[
            result["ts"] == pd.Timestamp("2026-07-19T08:00:00+08:00")
        ].iloc[0]
        row_0805 = result[
            result["ts"] == pd.Timestamp("2026-07-19T08:05:00+08:00")
        ].iloc[0]
        assert row_0800["price_mwh"] == 100.0
        assert pd.isna(row_0805["price_mwh"])
