"""Tests for ecolens.ingestion.storage.mongo.bulk_upsert and
ecolens.ingestion.storage.settings.MongoSettings source helpers.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ecolens.ingestion.storage.mongo import bulk_upsert
from ecolens.ingestion.storage.settings import MongoSettings, get_mongo_settings


class TestMongoSettingsSourceHelpers:
    def test_collection_for_known_sources(self):
        settings = MongoSettings()
        assert (
            settings.collection_for_source("openelectricity")
            == "openelectricity_responses"
        )
        assert settings.collection_for_source("aemo_nem") == "aemo_nem_dispatch"
        assert settings.collection_for_source("aemo_wem") == "aemo_wem_dispatch"

    def test_collection_for_unknown_source_raises_keyerror(self):
        settings = MongoSettings()
        with pytest.raises(KeyError, match="Unknown source"):
            settings.collection_for_source("not_a_real_source")

    def test_unique_key_for_known_sources(self):
        settings = MongoSettings()
        assert settings.unique_key_for_source("openelectricity") == (
            "network_code",
            "ts",
        )
        assert settings.unique_key_for_source("aemo_nem") == ("region", "ts")
        assert settings.unique_key_for_source("aemo_wem") == ("ts",)

    def test_unique_key_for_unknown_source_raises_keyerror(self):
        settings = MongoSettings()
        with pytest.raises(KeyError, match="Unknown source"):
            settings.unique_key_for_source("not_a_real_source")

    def test_get_mongo_settings_is_cached_singleton(self):
        get_mongo_settings.cache_clear()
        first = get_mongo_settings()
        second = get_mongo_settings()
        assert first is second
        get_mongo_settings.cache_clear()


def _make_fake_db(upserted_count: int = 1, modified_count: int = 0):
    fake_result = MagicMock(
        upserted_count=upserted_count, modified_count=modified_count
    )
    fake_collection = MagicMock()
    fake_collection.bulk_write = AsyncMock(return_value=fake_result)
    fake_db = MagicMock()
    fake_db.__getitem__ = MagicMock(return_value=fake_collection)
    return fake_db, fake_collection


class TestBulkUpsert:
    @pytest.mark.asyncio
    async def test_empty_docs_short_circuits_without_touching_db(self):
        fake_db, fake_collection = _make_fake_db()
        result = await bulk_upsert(fake_db, "openelectricity", [], "run-1")
        assert result == 0
        fake_collection.bulk_write.assert_not_called()

    @pytest.mark.asyncio
    async def test_stamps_ingest_metadata_on_every_doc(self):
        fake_db, fake_collection = _make_fake_db(upserted_count=2)
        docs = [
            {"network_code": "NEM", "ts": "t1"},
            {"network_code": "WEM", "ts": "t2"},
        ]
        await bulk_upsert(fake_db, "openelectricity", docs, "run-123")
        for doc in docs:
            assert doc["ingest_run_id"] == "run-123"
            assert doc["source"] == "openelectricity"
            assert "fetched_at" in doc

    @pytest.mark.asyncio
    async def test_builds_updateone_ops_keyed_on_source_unique_key(self):
        fake_db, fake_collection = _make_fake_db()
        docs = [{"network_code": "NEM", "ts": "t1", "wind_mw": 5.0}]
        await bulk_upsert(fake_db, "openelectricity", docs, "run-1")

        fake_collection.bulk_write.assert_called_once()
        ops = fake_collection.bulk_write.call_args.args[0]
        assert len(ops) == 1
        op = ops[0]
        assert op._filter == {"network_code": "NEM", "ts": "t1"}
        assert op._upsert is True

    @pytest.mark.asyncio
    async def test_returns_upserted_plus_modified_count(self):
        fake_db, _ = _make_fake_db(upserted_count=3, modified_count=2)
        docs = [{"region": "NEM", "ts": "t1"}]
        result = await bulk_upsert(fake_db, "aemo_nem", docs, "run-1")
        assert result == 5

    @pytest.mark.asyncio
    async def test_uses_correct_collection_for_source(self):
        fake_db, _ = _make_fake_db()
        docs = [{"ts": "t1"}]
        await bulk_upsert(fake_db, "aemo_wem", docs, "run-1")
        fake_db.__getitem__.assert_called_with("aemo_wem_dispatch")

    @pytest.mark.asyncio
    async def test_unknown_source_raises_before_any_db_call(self):
        fake_db, fake_collection = _make_fake_db()
        with pytest.raises(KeyError):
            await bulk_upsert(fake_db, "not_a_real_source", [{"ts": "t1"}], "run-1")
        fake_collection.bulk_write.assert_not_called()
