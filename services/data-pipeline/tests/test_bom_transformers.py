"""Unit tests for ecolens.ingestion.sources.bom.transformers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from ecolens.ingestion.sources.bom.schema import DEFAULT_BOM_STATIONS
from ecolens.ingestion.sources.bom.transformers import (
    apply_data_quality_fixes,
    diagnose,
    normalize_observation,
    synthetic_stub,
)


def _make_doc(**overrides) -> dict:
    base = {
        "ts": datetime.now(timezone.utc),
        "region": "NSW1",
        "station_id": "066037",
        "station_name": "Sydney",
        "schema_version": "1.0",
        "temp_c": 22.0,
        "apparent_temp_c": 22.0,
        "dew_point_c": 15.0,
        "humidity_pct": 50.0,
        "wind_speed_kmh": 10.0,
        "wind_direction_deg": 90.0,
        "wind_gust_kmh": 20.0,
        "pressure_hpa": 1013.0,
        "rain_since_9am_mm": 0.0,
        "rain_last_hour_mm": None,
        "cloud_oktas": 4.0,
        "cloud_cover_pct": 50.0,
        "data_quality_status": "preliminary",
        "source": "bom",
        "ingest_run_id": "test",
        "ingested_at": None,
        "fetched_at": None,
    }
    base.update(overrides)
    return base


def _v1_payload(**data_overrides) -> dict:
    data = {
        "temp": 28.5,
        "temp_feels_like": 30.1,
        "humidity": 45,
        "wind": {"speed_kilometre": 15.0, "speed_knot": 8, "direction": "W"},
        "gust": None,
        "rain_since_9am": 2.4,
        "station": {"bom_id": "066214", "name": "Sydney - Observatory Hill"},
    }
    data.update(data_overrides)
    return {
        "metadata": {"observation_time": "2026-07-20T14:00:00Z"},
        "data": data,
    }


class TestNormalizeObservation:
    def test_maps_bom_fields_to_v1_row(self):
        now = pd.Timestamp.now(tz="UTC")
        row = normalize_observation(_v1_payload(), "NSW1", "r3gx2s", now)
        assert row is not None
        assert row["region"] == "NSW1"
        assert row["station_id"] == "066214"
        assert row["station_name"] == "Sydney - Observatory Hill"
        assert row["temp_c"] == 28.5
        assert row["wind_direction_deg"] == 270.0  # "W"
        assert row["dew_point_c"] is not None  # derived via Magnus, not from the API
        assert row["ts"].minute in (0, 30)

    def test_missing_observation_time_returns_none(self):
        now = pd.Timestamp.now(tz="UTC")
        payload = _v1_payload()
        payload["metadata"] = {}
        row = normalize_observation(payload, "NSW1", "r3gx2s", now)
        assert row is None

    def test_empty_data_returns_none(self):
        now = pd.Timestamp.now(tz="UTC")
        row = normalize_observation({"metadata": {}, "data": {}}, "NSW1", "r3gx2s", now)
        assert row is None

    def test_null_gust_leaves_wind_gust_none(self):
        now = pd.Timestamp.now(tz="UTC")
        row = normalize_observation(_v1_payload(gust=None), "NSW1", "r3gx2s", now)
        assert row is not None
        assert row["wind_gust_kmh"] is None

    def test_missing_station_falls_back_to_geohash(self):
        now = pd.Timestamp.now(tz="UTC")
        row = normalize_observation(_v1_payload(station={}), "NSW1", "r3gx2s", now)
        assert row is not None
        assert row["station_id"] == "r3gx2s"

    def test_cloud_and_pressure_always_none(self):
        # Not present in the v1 API response at all -- see
        # bom_obserbation.md §4 "Known caveats".
        now = pd.Timestamp.now(tz="UTC")
        row = normalize_observation(_v1_payload(), "NSW1", "r3gx2s", now)
        assert row is not None
        assert row["cloud_cover_pct"] is None
        assert row["cloud_oktas"] is None
        assert row["pressure_hpa"] is None


class TestSyntheticStub:
    def test_produces_docs_for_all_six_regions(self):
        since = datetime.now(timezone.utc) - timedelta(hours=2)
        until = datetime.now(timezone.utc)
        docs = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        regions = {d["region"] for d in docs}
        assert regions == {"NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"}

    def test_timestamps_are_30_min_aligned(self):
        since = datetime.now(timezone.utc) - timedelta(hours=2)
        until = datetime.now(timezone.utc)
        docs = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        for d in docs:
            assert d["ts"].minute in (0, 30)

    def test_deterministic(self):
        since = datetime.now(timezone.utc) - timedelta(hours=2)
        until = datetime.now(timezone.utc)
        docs1 = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        docs2 = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        for d1, d2 in zip(docs1, docs2):
            assert d1["temp_c"] == d2["temp_c"]
            assert d1["humidity_pct"] == d2["humidity_pct"]
            assert d1["region"] == d2["region"]

    def test_temp_within_realistic_range(self):
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        until = datetime.now(timezone.utc)
        docs = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        temps = [d["temp_c"] for d in docs if d["temp_c"] is not None]
        assert min(temps) > -5
        assert max(temps) < 50

    def test_humidity_in_valid_range(self):
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        until = datetime.now(timezone.utc)
        docs = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        hums = [d["humidity_pct"] for d in docs if d["humidity_pct"] is not None]
        for h in hums:
            assert 0 <= h <= 100

    def test_wind_speed_non_negative(self):
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        until = datetime.now(timezone.utc)
        docs = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        winds = [d["wind_speed_kmh"] for d in docs if d["wind_speed_kmh"] is not None]
        for w in winds:
            assert w >= 0

    def test_seasonal_pattern_brisbane_warmer_than_hobart(self):
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        until = datetime.now(timezone.utc)
        docs = synthetic_stub(DEFAULT_BOM_STATIONS, since, until)
        qld = np.mean([d["temp_c"] for d in docs if d["region"] == "QLD1"])
        tas = np.mean([d["temp_c"] for d in docs if d["region"] == "TAS1"])
        assert qld > tas


class TestApplyDataQualityFixes:
    def test_nan_becomes_none(self):
        doc = _make_doc(temp_c=float("nan"))
        result = apply_data_quality_fixes([doc])
        assert result[0]["temp_c"] is None
        assert result[0]["humidity_pct"] == 50.0

    def test_temp_clamped_to_max(self):
        doc = _make_doc(temp_c=99.0)
        result = apply_data_quality_fixes([doc])
        assert result[0]["temp_c"] == 50.0

    def test_humidity_clamped_to_100(self):
        doc = _make_doc(humidity_pct=150.0)
        result = apply_data_quality_fixes([doc])
        assert result[0]["humidity_pct"] == 100.0

    def test_wind_speed_clamped_to_min(self):
        doc = _make_doc(wind_speed_kmh=-5.0)
        result = apply_data_quality_fixes([doc])
        assert result[0]["wind_speed_kmh"] == 0.0

    @pytest.mark.parametrize(
        ("wd", "expected"),
        [(400.0, 40.0), (720.0, 0.0), (360.0, 0.0), (359.9, 359.9), (-90.0, 270.0)],
    )
    def test_wind_direction_wraps_at_360(self, wd, expected):
        doc = _make_doc(wind_direction_deg=wd)
        result = apply_data_quality_fixes([doc])
        assert result[0]["wind_direction_deg"] == expected

    def test_pressure_clamped(self):
        doc = _make_doc(pressure_hpa=1500.0)
        result = apply_data_quality_fixes([doc])
        assert result[0]["pressure_hpa"] == 1084.0

    def test_cloud_oktas_clamped(self):
        doc = _make_doc(cloud_oktas=12.0)
        result = apply_data_quality_fixes([doc])
        assert result[0]["cloud_oktas"] == 8.0

    def test_rain_clamped(self):
        doc = _make_doc(rain_since_9am_mm=2000.0)
        result = apply_data_quality_fixes([doc])
        assert result[0]["rain_since_9am_mm"] == 500.0

    def test_rain_last_hour_computed_from_delta(self):
        base = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
        doc1 = _make_doc(ts=base, rain_since_9am_mm=10.0)
        doc2 = _make_doc(ts=base + timedelta(hours=1), rain_since_9am_mm=15.0)
        result = apply_data_quality_fixes([doc1, doc2])
        r2 = next(d for d in result if d["ts"] == base + timedelta(hours=1))
        assert r2["rain_last_hour_mm"] == 5.0

    def test_rain_reset_at_9am(self):
        base = datetime(2024, 1, 1, 9, 0, tzinfo=timezone.utc)
        doc1 = _make_doc(ts=base, rain_since_9am_mm=10.0)
        doc2 = _make_doc(ts=base + timedelta(hours=1), rain_since_9am_mm=2.0)
        result = apply_data_quality_fixes([doc1, doc2])
        r2 = next(d for d in result if d["ts"] == base + timedelta(hours=1))
        assert r2["rain_last_hour_mm"] == 0.0


class TestDiagnose:
    def test_runs_without_error(self):
        diagnose([])
        diagnose([_make_doc()])
