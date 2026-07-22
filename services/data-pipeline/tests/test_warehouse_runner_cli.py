"""Tests for ecolens.warehouse.runner.cli argument parsing."""

from __future__ import annotations

import sys

import pytest

from ecolens.warehouse.runner.cli import parse_args


class TestParseArgs:
    def test_default_mode_is_incremental(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["runner.py"])
        args = parse_args()
        assert args.incremental is True
        assert args.full is False
        assert args.validate_only is False

    def test_full_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["runner.py", "--full"])
        args = parse_args()
        assert args.full is True

    def test_validate_only_flag(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["runner.py", "--validate-only"])
        args = parse_args()
        assert args.validate_only is True

    def test_full_and_validate_only_are_mutually_exclusive(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["runner.py", "--full", "--validate-only"])
        with pytest.raises(SystemExit):
            parse_args()

    def test_select_accepts_multiple_values(self, monkeypatch):
        monkeypatch.setattr(
            sys,
            "argv",
            ["runner.py", "--select", "tag:ml_features", "+fact_demand_30min"],
        )
        args = parse_args()
        assert args.select == ["tag:ml_features", "+fact_demand_30min"]

    def test_skip_flags_default_false(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["runner.py"])
        args = parse_args()
        assert args.skip_aggregates is False
        assert args.skip_archive is False
