"""Tests for ecolens.ingestion.core.run_history.

Every test scopes `IngestionSettings.ingestion_runs_log_path` to a
`tmp_path` file -- never touches the real repo's
`data/log/ingestion-runs.jsonl`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from ecolens.ingestion.core.run_history import (
    compute_stats,
    last_run,
    read_runs,
    record_run,
)
from ecolens.ingestion.core.settings import IngestionSettings

NOW = datetime(2026, 7, 29, 12, 0, tzinfo=timezone.utc)


def _settings(tmp_path: Path) -> IngestionSettings:
    return IngestionSettings(ingestion_runs_log_path=tmp_path / "ingestion-runs.jsonl")


class TestRecordAndReadRuns:
    def test_round_trips_through_a_fresh_read(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW - timedelta(seconds=1),
            finished_at=NOW,
            records_fetched=10,
            records_inserted=10,
            anomalies_flagged=1,
            settings=settings,
        )
        runs = read_runs("aemo_nem", settings=settings)
        assert len(runs) == 1
        assert runs[0].status == "success"
        assert runs[0].records_fetched == 10
        assert runs[0].anomalies_flagged == 1

    def test_no_file_returns_empty_list(self, tmp_path: Path):
        settings = _settings(tmp_path)
        assert read_runs("aemo_nem", settings=settings) == []

    def test_corrupt_line_is_skipped_not_a_crash(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW,
            finished_at=NOW,
            settings=settings,
        )
        settings.ingestion_runs_log_path.write_text(
            settings.ingestion_runs_log_path.read_text() + "{not valid json\n"
        )
        runs = read_runs("aemo_nem", settings=settings)
        assert len(runs) == 1  # the one good line survives

    def test_filters_by_source(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW,
            finished_at=NOW,
            settings=settings,
        )
        record_run(
            "bom", status="success", started_at=NOW, finished_at=NOW, settings=settings
        )
        assert len(read_runs("aemo_nem", settings=settings)) == 1
        assert len(read_runs("bom", settings=settings)) == 1
        assert len(read_runs(settings=settings)) == 2

    def test_filters_by_since(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW - timedelta(days=10),
            finished_at=NOW - timedelta(days=10),
            settings=settings,
        )
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW,
            finished_at=NOW,
            settings=settings,
        )
        recent = read_runs("aemo_nem", since=NOW - timedelta(days=1), settings=settings)
        assert len(recent) == 1

    def test_duration_ms_computed_from_started_finished(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW,
            finished_at=NOW + timedelta(milliseconds=479),
            settings=settings,
        )
        assert read_runs("aemo_nem", settings=settings)[0].duration_ms == 479.0


class TestLastRun:
    def test_none_when_no_runs(self, tmp_path: Path):
        settings = _settings(tmp_path)
        assert last_run("aemo_nem", settings=settings) is None

    def test_returns_the_most_recent(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="failed",
            started_at=NOW - timedelta(hours=1),
            finished_at=NOW - timedelta(hours=1),
            error="boom",
            settings=settings,
        )
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW,
            finished_at=NOW,
            settings=settings,
        )
        latest = last_run("aemo_nem", settings=settings)
        assert latest is not None
        assert latest.status == "success"


class TestComputeStats:
    def test_no_runs_gives_all_none(self, tmp_path: Path):
        settings = _settings(tmp_path)
        stats = compute_stats(
            "aemo_nem", since=NOW - timedelta(days=1), settings=settings
        )
        assert stats.n_runs == 0
        assert stats.success_rate_pct is None
        assert stats.p50_duration_ms is None

    def test_success_rate_counts_empty_as_non_failure(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW,
            finished_at=NOW,
            settings=settings,
        )
        record_run(
            "aemo_nem",
            status="empty",
            started_at=NOW,
            finished_at=NOW,
            settings=settings,
        )
        record_run(
            "aemo_nem",
            status="failed",
            started_at=NOW,
            finished_at=NOW,
            error="x",
            settings=settings,
        )
        stats = compute_stats(
            "aemo_nem", since=NOW - timedelta(days=1), settings=settings
        )
        assert stats.n_runs == 3
        # 2 of 3 (success + empty) count as non-failures.
        assert stats.success_rate_pct == round(2 / 3 * 100, 1)

    def test_percentiles_over_known_durations(self, tmp_path: Path):
        settings = _settings(tmp_path)
        for ms in [100, 200, 300, 400, 500]:
            record_run(
                "aemo_nem",
                status="success",
                started_at=NOW,
                finished_at=NOW + timedelta(milliseconds=ms),
                settings=settings,
            )
        stats = compute_stats(
            "aemo_nem", since=NOW - timedelta(days=1), settings=settings
        )
        assert stats.p50_duration_ms == 300.0
        assert stats.p99_duration_ms is not None
        assert stats.p50_duration_ms <= stats.p95_duration_ms <= stats.p99_duration_ms

    def test_only_counts_runs_within_the_window(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW - timedelta(days=10),
            finished_at=NOW - timedelta(days=10),
            settings=settings,
        )
        stats = compute_stats(
            "aemo_nem", since=NOW - timedelta(hours=1), settings=settings
        )
        assert stats.n_runs == 0

    def test_scoped_to_one_source(self, tmp_path: Path):
        settings = _settings(tmp_path)
        record_run(
            "aemo_nem",
            status="success",
            started_at=NOW,
            finished_at=NOW,
            settings=settings,
        )
        record_run(
            "bom",
            status="failed",
            started_at=NOW,
            finished_at=NOW,
            error="x",
            settings=settings,
        )
        stats = compute_stats(
            "aemo_nem", since=NOW - timedelta(days=1), settings=settings
        )
        assert stats.n_runs == 1
        assert stats.success_rate_pct == 100.0
