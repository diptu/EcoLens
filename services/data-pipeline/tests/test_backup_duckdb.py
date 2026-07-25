"""Tests for scripts/backup_duckdb.py and scripts/restore_duckdb.py.

Real write -> real backup (EXPORT DATABASE) -> real restore (IMPORT
DATABASE) roundtrip against tmp_path DuckDB files -- no mocks, since a
backup/restore path is exactly the kind of thing where a mock would
happily assert against a call signature while the actual SQL silently
produces an empty or corrupt snapshot.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from backup_duckdb import _prune_old_snapshots, backup  # noqa: E402
from restore_duckdb import list_snapshots, restore  # noqa: E402

from ecolens.ingestion.storage.duckdb_store import write_historical  # noqa: E402


def _doc(station_id: str, ts: datetime, temp_c: float) -> dict:
    return {
        "station_id": station_id,
        "ts": ts,
        "region": "NSW1",
        "temp_c": temp_c,
        "source": "open_meteo_era5",
    }


class TestBackup:
    def test_missing_source_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            backup(
                path=tmp_path / "nonexistent.duckdb",
                backup_dir=tmp_path / "backups",
                keep=14,
            )

    def test_snapshot_contains_written_rows(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical(
            "bom",
            [
                _doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0),
                _doc("066037", datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc), 21.0),
            ],
            db_path=db_path,
        )

        backup_dir = tmp_path / "backups"
        snapshot_dir = backup(path=db_path, backup_dir=backup_dir, keep=14)

        assert snapshot_dir.exists()
        assert (snapshot_dir / "schema.sql").exists()
        assert any(snapshot_dir.glob("*.parquet"))

    def test_backup_is_read_only_and_leaves_source_writable(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical(
            "bom",
            [_doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0)],
            db_path=db_path,
        )
        backup(path=db_path, backup_dir=tmp_path / "backups", keep=14)

        # source file must still be writable after the backup connection closes
        written = write_historical(
            "bom",
            [_doc("066037", datetime(2024, 1, 2, tzinfo=timezone.utc), 22.0)],
            db_path=db_path,
        )
        assert written == 1


class TestPruneOldSnapshots:
    def test_keeps_only_the_n_most_recent(self, tmp_path: Path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        for name in ["20260101T000000Z", "20260102T000000Z", "20260103T000000Z"]:
            (backup_dir / name).mkdir()

        removed = _prune_old_snapshots(backup_dir, keep=2)

        assert [d.name for d in removed] == ["20260101T000000Z"]
        remaining = sorted(d.name for d in backup_dir.iterdir())
        assert remaining == ["20260102T000000Z", "20260103T000000Z"]

    def test_keep_zero_removes_everything(self, tmp_path: Path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "20260101T000000Z").mkdir()

        removed = _prune_old_snapshots(backup_dir, keep=0)

        assert len(removed) == 1
        assert list(backup_dir.iterdir()) == []

    def test_backup_prunes_older_snapshots_automatically(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical(
            "bom",
            [_doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0)],
            db_path=db_path,
        )
        backup_dir = tmp_path / "backups"

        # pre-seed 3 fake old snapshot dirs so keep=1 has something to prune
        for name in ["20250101T000000Z", "20250102T000000Z", "20250103T000000Z"]:
            (backup_dir / name).mkdir(parents=True)

        backup(path=db_path, backup_dir=backup_dir, keep=1)

        remaining = sorted(d.name for d in backup_dir.iterdir())
        assert len(remaining) == 1
        # the real, just-created snapshot (newest name) must be the survivor
        assert remaining[0] not in {
            "20250101T000000Z",
            "20250102T000000Z",
            "20250103T000000Z",
        }


class TestRestoreRoundTrip:
    def test_restored_file_matches_source_data(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        docs = [
            _doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0),
            _doc("066037", datetime(2024, 1, 1, 0, 30, tzinfo=timezone.utc), 21.0),
        ]
        write_historical("bom", docs, db_path=db_path)

        snapshot_dir = backup(path=db_path, backup_dir=tmp_path / "backups", keep=14)

        restored_path = tmp_path / "restored.duckdb"
        restore(snapshot=snapshot_dir, target=restored_path)

        con = duckdb.connect(str(restored_path), read_only=True)
        try:
            rows = con.execute(
                "SELECT station_id, temp_c FROM bom_observations ORDER BY temp_c"
            ).fetchall()
        finally:
            con.close()
        assert rows == [("066037", 20.0), ("066037", 21.0)]

    def test_restore_missing_snapshot_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            restore(
                snapshot=tmp_path / "nonexistent_snapshot",
                target=tmp_path / "out.duckdb",
            )

    def test_restore_refuses_to_overwrite_without_force(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical(
            "bom",
            [_doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0)],
            db_path=db_path,
        )
        snapshot_dir = backup(path=db_path, backup_dir=tmp_path / "backups", keep=14)

        target = tmp_path / "restored.duckdb"
        target.write_bytes(b"pre-existing file, must survive")

        with pytest.raises(FileExistsError):
            restore(snapshot=snapshot_dir, target=target)
        assert target.read_bytes() == b"pre-existing file, must survive"

    def test_restore_force_overwrites(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical(
            "bom",
            [_doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0)],
            db_path=db_path,
        )
        snapshot_dir = backup(path=db_path, backup_dir=tmp_path / "backups", keep=14)

        target = tmp_path / "restored.duckdb"
        target.write_bytes(b"stale content")

        restore(snapshot=snapshot_dir, target=target, force=True)

        con = duckdb.connect(str(target), read_only=True)
        try:
            count = con.execute("SELECT count(*) FROM bom_observations").fetchone()
        finally:
            con.close()
        assert count == (1,)


class TestListSnapshots:
    def test_no_backup_dir_returns_empty(self, tmp_path: Path):
        assert list_snapshots(tmp_path / "does_not_exist") == []

    def test_lists_sorted_chronologically(self, tmp_path: Path):
        backup_dir = tmp_path / "backups"
        for name in ["20260103T000000Z", "20260101T000000Z", "20260102T000000Z"]:
            (backup_dir / name).mkdir(parents=True)

        names = [d.name for d in list_snapshots(backup_dir)]
        assert names == ["20260101T000000Z", "20260102T000000Z", "20260103T000000Z"]


class TestCli:
    """End-to-end subprocess runs -- exercises the real argparse wiring
    (including --snapshot-name, the flag the Makefile's restore-duckdb
    target depends on) rather than just the imported functions.
    """

    _scripts_dir = Path(__file__).resolve().parents[1] / "scripts"

    def test_backup_then_restore_by_snapshot_name(self, tmp_path: Path):
        db_path = tmp_path / "historical.duckdb"
        write_historical(
            "bom",
            [_doc("066037", datetime(2024, 1, 1, tzinfo=timezone.utc), 20.0)],
            db_path=db_path,
        )
        backup_dir = tmp_path / "backups"

        backup_result = subprocess.run(
            [
                sys.executable,
                str(self._scripts_dir / "backup_duckdb.py"),
                "--path",
                str(db_path),
                "--backup-dir",
                str(backup_dir),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        snapshot_name = sorted(d.name for d in backup_dir.iterdir())[-1]
        assert snapshot_name in backup_result.stdout

        target = tmp_path / "restored.duckdb"
        subprocess.run(
            [
                sys.executable,
                str(self._scripts_dir / "restore_duckdb.py"),
                "--backup-dir",
                str(backup_dir),
                "--snapshot-name",
                snapshot_name,
                "--target",
                str(target),
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        con = duckdb.connect(str(target), read_only=True)
        try:
            count = con.execute("SELECT count(*) FROM bom_observations").fetchone()
        finally:
            con.close()
        assert count == (1,)

    def test_list_flag_prints_snapshot_names(self, tmp_path: Path):
        backup_dir = tmp_path / "backups"
        (backup_dir / "20260101T000000Z").mkdir(parents=True)

        result = subprocess.run(
            [
                sys.executable,
                str(self._scripts_dir / "restore_duckdb.py"),
                "--backup-dir",
                str(backup_dir),
                "--list",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        assert "20260101T000000Z" in result.stdout
