"""Tests for ecolens.ingestion.core.data_source_overrides.

Every test scopes `IngestionSettings.data_source_overrides_path` to a
`tmp_path` file (passed explicitly via `settings=`) -- never touches
the real repo's `data/data_source_overrides.json`.
"""

from __future__ import annotations

from pathlib import Path

from ecolens.ingestion.core.data_source_overrides import (
    DEFAULT_CRON_EXPRESSION,
    DEFAULT_TIMEZONE,
    SOURCE_IDS,
    SOURCE_LABELS,
    get_override,
    is_source_enabled,
    set_override,
    validate_cron_expression,
    validate_timezone,
)
from ecolens.ingestion.core.settings import IngestionSettings


def _settings(tmp_path: Path) -> IngestionSettings:
    return IngestionSettings(
        data_source_overrides_path=tmp_path / "data_source_overrides.json"
    )


class TestCanonicalSources:
    def test_five_real_sources_not_the_todo_s_literal_nine(self):
        assert len(SOURCE_IDS) == 5
        assert set(SOURCE_IDS) == {
            "aemo_nem",
            "aemo_wem",
            "openelectricity",
            "bom",
            "aemo_holidays",
        }

    def test_every_source_has_a_label(self):
        for source_id in SOURCE_IDS:
            assert SOURCE_LABELS[source_id]


class TestGetOverride:
    def test_defaults_when_no_file_exists(self, tmp_path: Path):
        settings = _settings(tmp_path)
        override = get_override("aemo_nem", settings=settings)
        assert override.enabled is True
        assert override.cron is None
        assert override.timezone == DEFAULT_TIMEZONE
        assert override.description is None
        assert override.auth_type is None
        assert override.metadata == {}
        assert override.version == 1
        assert override.updated_at is None

    def test_defaults_for_a_source_never_patched_even_if_file_exists(
        self, tmp_path: Path
    ):
        settings = _settings(tmp_path)
        set_override("bom", enabled=False, settings=settings)
        override = get_override("aemo_nem", settings=settings)
        assert override.enabled is True  # untouched, still default

    def test_corrupt_file_degrades_to_defaults_not_a_crash(self, tmp_path: Path):
        settings = _settings(tmp_path)
        settings.data_source_overrides_path.parent.mkdir(parents=True, exist_ok=True)
        settings.data_source_overrides_path.write_text("{not valid json")
        override = get_override("aemo_nem", settings=settings)
        assert override.enabled is True


class TestSetOverride:
    def test_persists_across_a_fresh_read(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", enabled=False, settings=settings)
        override = get_override("aemo_nem", settings=settings)
        assert override.enabled is False

    def test_setting_cron_alone_does_not_touch_enabled(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", enabled=False, settings=settings)
        set_override("aemo_nem", cron="0 * * * *", settings=settings)
        override = get_override("aemo_nem", settings=settings)
        assert override.enabled is False
        assert override.cron == "0 * * * *"

    def test_stamps_updated_at(self, tmp_path: Path):
        settings = _settings(tmp_path)
        override = set_override("aemo_nem", enabled=False, settings=settings)
        assert override.updated_at is not None

    def test_only_touches_the_given_source(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("bom", enabled=False, settings=settings)
        assert get_override("aemo_nem", settings=settings).enabled is True
        assert get_override("bom", settings=settings).enabled is False


class TestIsSourceEnabled:
    def test_true_by_default(self, tmp_path: Path):
        settings = _settings(tmp_path)
        assert is_source_enabled("aemo_nem", settings=settings) is True

    def test_false_after_disabling(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", enabled=False, settings=settings)
        assert is_source_enabled("aemo_nem", settings=settings) is False

    def test_true_again_after_re_enabling(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", enabled=False, settings=settings)
        set_override("aemo_nem", enabled=True, settings=settings)
        assert is_source_enabled("aemo_nem", settings=settings) is True


class TestSetOverrideExtendedFields:
    def test_timezone_persists(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", timezone_name="America/New_York", settings=settings)
        assert (
            get_override("aemo_nem", settings=settings).timezone == "America/New_York"
        )

    def test_description_persists(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", description="custom description", settings=settings)
        assert (
            get_override("aemo_nem", settings=settings).description
            == "custom description"
        )

    def test_auth_type_persists(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("openelectricity", auth_type="none", settings=settings)
        assert get_override("openelectricity", settings=settings).auth_type == "none"

    def test_metadata_merges_not_replaces(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", metadata={"a": 1}, settings=settings)
        set_override("aemo_nem", metadata={"b": 2}, settings=settings)
        override = get_override("aemo_nem", settings=settings)
        assert override.metadata == {"a": 1, "b": 2}

    def test_metadata_merge_overwrites_an_existing_key(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", metadata={"a": 1}, settings=settings)
        set_override("aemo_nem", metadata={"a": 2}, settings=settings)
        assert get_override("aemo_nem", settings=settings).metadata == {"a": 2}

    def test_version_starts_at_one_and_increments_on_every_patch(self, tmp_path: Path):
        settings = _settings(tmp_path)
        assert get_override("aemo_nem", settings=settings).version == 1
        first = set_override("aemo_nem", enabled=False, settings=settings)
        assert first.version == 2
        second = set_override("aemo_nem", cron="0 * * * *", settings=settings)
        assert second.version == 3

    def test_version_is_independent_per_source(self, tmp_path: Path):
        settings = _settings(tmp_path)
        set_override("aemo_nem", enabled=False, settings=settings)
        set_override("aemo_nem", enabled=True, settings=settings)
        assert get_override("aemo_nem", settings=settings).version == 3
        assert get_override("bom", settings=settings).version == 1


class TestValidateTimezone:
    def test_valid_iana_timezones(self):
        for tz in [DEFAULT_TIMEZONE, "UTC", "America/New_York", "Europe/London"]:
            assert validate_timezone(tz), tz

    def test_invalid_timezone(self):
        assert not validate_timezone("Not/AZone")

    def test_empty_string(self):
        assert not validate_timezone("")


class TestValidateCronExpression:
    def test_valid_expressions(self):
        for expr in [
            DEFAULT_CRON_EXPRESSION,
            "0 0 * * *",
            "0,30 8-17 * * 1-5",
            "* * * * *",
            "15 3 1 * *",
        ]:
            assert validate_cron_expression(expr), expr

    def test_wrong_field_count(self):
        assert not validate_cron_expression("* * * *")
        assert not validate_cron_expression("* * * * * *")

    def test_non_numeric_garbage(self):
        assert not validate_cron_expression("not a cron expression")

    def test_empty_string(self):
        assert not validate_cron_expression("")
