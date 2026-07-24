"""Tests for ecolens.ingestion.api (the /ingestion/historical endpoint).

Two layers:
  * `Test*` classes down to `TestDispatch` exercise the router: each
    `_ingest_*_historical` job function is monkeypatched to a spy (they
    fire real HTTP fetches against a *historical* Mongo cluster, out of
    scope here), so these verify request validation, the 503 when
    MONGO_URI_HISTORICAL isn't configured, and that the right job gets
    scheduled with the right (possibly normalized) date range. Same
    pattern as test_forecasting_api.py.
  * `TestIngest*Historical` classes test each job function's own body
    directly (fetch -> validate -> upsert), with the fetcher class,
    validator, `get_historical_db`, and `bulk_upsert` all monkeypatched
    -- still no real HTTP/MongoDB, just one layer deeper than the router
    tests above.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pandera.errors
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ecolens.ingestion import api as api_module
from ecolens.ingestion.storage.settings import get_mongo_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    # chdir to an empty tmp_path so MongoSettings' own env_file=".env"
    # never picks up this repo's real .env (which has a real
    # MONGO_URI_HISTORICAL) -- learned the hard way earlier this session
    # that a leaked real .env value silently changes test behavior.
    monkeypatch.chdir(tmp_path)
    get_mongo_settings.cache_clear()

    app = FastAPI()
    app.include_router(api_module.router)
    with TestClient(app) as c:
        yield c
    get_mongo_settings.cache_clear()


@pytest.fixture
def historical_mongo_configured(monkeypatch):
    monkeypatch.setenv("MONGO_URI_HISTORICAL", "mongodb://fake-historical:27017")
    get_mongo_settings.cache_clear()
    yield
    get_mongo_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_jobs():
    api_module._jobs.clear()
    yield
    api_module._jobs.clear()


class TestNoHistoricalMongoConfigured:
    def test_503s_without_calling_any_job(self, client, monkeypatch):
        called = {"ran": False}

        async def fake_job(start, end):
            called["ran"] = True

        monkeypatch.setattr(api_module, "_ingest_bom_historical", fake_job)
        response = client.post(
            "/ingestion/historical", params={"source": "bom", "date": "2026-01-01"}
        )
        assert response.status_code == 503
        assert called["ran"] is False


class TestRequestValidation:
    def test_date_and_range_together_422s(self, client, historical_mongo_configured):
        response = client.post(
            "/ingestion/historical",
            params={
                "source": "bom",
                "date": "2026-01-01",
                "start_date": "2026-01-02",
                "end_date": "2026-01-03",
            },
        )
        assert response.status_code == 422

    def test_neither_date_nor_range_422s(self, client, historical_mongo_configured):
        response = client.post("/ingestion/historical", params={"source": "bom"})
        assert response.status_code == 422

    def test_range_missing_end_date_422s(self, client, historical_mongo_configured):
        response = client.post(
            "/ingestion/historical",
            params={"source": "bom", "start_date": "2026-01-01"},
        )
        assert response.status_code == 422

    def test_end_before_start_422s(self, client, historical_mongo_configured):
        response = client.post(
            "/ingestion/historical",
            params={
                "source": "bom",
                "start_date": "2026-01-05",
                "end_date": "2026-01-01",
            },
        )
        assert response.status_code == 422

    def test_unknown_source_422s(self, client, historical_mongo_configured):
        response = client.post(
            "/ingestion/historical",
            params={"source": "not_a_real_source", "date": "2026-01-01"},
        )
        assert response.status_code == 422


class TestDispatch:
    def test_single_date_normalizes_to_a_one_day_range(
        self, client, historical_mongo_configured, monkeypatch
    ):
        calls = []

        async def fake_job(start, end):
            calls.append((start, end))

        monkeypatch.setattr(api_module, "_ingest_bom_historical", fake_job)
        response = client.post(
            "/ingestion/historical", params={"source": "bom", "date": "2026-01-01"}
        )

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body.pop("job_id"), str)
        assert body == {
            "status": "started",
            "source": "bom",
            "start_date": "2026-01-01",
            "end_date": "2026-01-01",
        }
        assert calls == [(date(2026, 1, 1), date(2026, 1, 1))]

    def test_range_dispatches_with_start_and_end(
        self, client, historical_mongo_configured, monkeypatch
    ):
        calls = []

        async def fake_job(start, end):
            calls.append((start, end))

        monkeypatch.setattr(api_module, "_ingest_bom_historical", fake_job)
        response = client.post(
            "/ingestion/historical",
            params={
                "source": "bom",
                "start_date": "2026-01-01",
                "end_date": "2026-01-05",
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["start_date"] == "2026-01-01"
        assert body["end_date"] == "2026-01-05"
        assert len(calls) == 1

    @pytest.mark.parametrize("source", ["aemo_nem", "aemo_wem"])
    def test_aemo_sources_dispatch_with_source_name(
        self, client, historical_mongo_configured, monkeypatch, source
    ):
        calls = []

        async def fake_job(src, start, end):
            calls.append((src, start, end))

        monkeypatch.setattr(api_module, "_ingest_aemo_historical", fake_job)
        response = client.post(
            "/ingestion/historical",
            params={"source": source, "date": "2026-01-01"},
        )

        assert response.status_code == 200
        assert len(calls) == 1
        assert calls[0][0] == source

    def test_openelectricity_dispatches(
        self, client, historical_mongo_configured, monkeypatch
    ):
        calls = []

        async def fake_job(start, end):
            calls.append((start, end))

        monkeypatch.setattr(api_module, "_ingest_openelectricity_historical", fake_job)
        response = client.post(
            "/ingestion/historical",
            params={"source": "openelectricity", "date": "2026-01-01"},
        )

        assert response.status_code == 200
        assert len(calls) == 1

    def test_holidays_dispatches(
        self, client, historical_mongo_configured, monkeypatch
    ):
        calls = []

        async def fake_job(start, end):
            calls.append((start, end))

        monkeypatch.setattr(api_module, "_ingest_holidays_historical", fake_job)
        response = client.post(
            "/ingestion/historical",
            params={"source": "holidays", "date": "2026-01-01"},
        )

        assert response.status_code == 200
        assert len(calls) == 1


class TestJobStatusPolling:
    def test_completed_job_reports_upserted_count(
        self, client, historical_mongo_configured, monkeypatch
    ):
        async def fake_job(start, end):
            return 7

        monkeypatch.setattr(api_module, "_ingest_bom_historical", fake_job)
        trigger = client.post(
            "/ingestion/historical", params={"source": "bom", "date": "2026-01-01"}
        )
        job_id = trigger.json()["job_id"]

        status = client.get(f"/ingestion/historical/{job_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "completed"
        assert body["upserted"] == 7
        assert body["error"] is None
        assert body["finished_at"] is not None

    def test_failed_job_reports_error(
        self, client, historical_mongo_configured, monkeypatch
    ):
        async def fake_job(start, end):
            raise RuntimeError("boom")

        monkeypatch.setattr(api_module, "_ingest_bom_historical", fake_job)
        trigger = client.post(
            "/ingestion/historical", params={"source": "bom", "date": "2026-01-01"}
        )
        job_id = trigger.json()["job_id"]

        status = client.get(f"/ingestion/historical/{job_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "failed"
        assert body["error"] == "boom"
        assert body["upserted"] is None

    def test_unknown_job_id_404s(self, client):
        response = client.get("/ingestion/historical/no-such-job")
        assert response.status_code == 404


class TestIngestBomHistorical:
    def _patch(self, monkeypatch, *, docs, validate_error=False):
        fake_fetcher = MagicMock()
        fake_fetcher.fetch_all_stations_for_range = AsyncMock(return_value=docs)
        monkeypatch.setattr(
            api_module, "HistoricalFetcher", MagicMock(return_value=fake_fetcher)
        )
        monkeypatch.setattr(api_module, "get_historical_db", lambda: object())
        bulk_upsert = AsyncMock(return_value=len(docs))
        monkeypatch.setattr(api_module, "bulk_upsert", bulk_upsert)
        # Mocked in every _patch() across this file's TestIngest*Historical
        # classes so a real DuckDB file never gets written as a side
        # effect of running the test suite -- these classes call the
        # _ingest_*_historical functions directly (not through the
        # `client` fixture's tmp_path chdir), so without this the default
        # historical_duckdb_path would resolve against pytest's real cwd.
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", MagicMock(return_value=0)
        )

        if validate_error:
            monkeypatch.setattr(
                api_module,
                "validate_bom",
                MagicMock(side_effect=pandera.errors.SchemaError(None, None, "bad")),
            )
        else:
            monkeypatch.setattr(api_module, "validate_bom", lambda d: d)
        return bulk_upsert

    @pytest.mark.asyncio
    async def test_happy_path_upserts_into_historical_db(self, monkeypatch):
        bulk_upsert = self._patch(monkeypatch, docs=[{"station_id": "1", "ts": "t"}])
        await api_module._ingest_bom_historical(date(2026, 1, 1), date(2026, 1, 2))
        bulk_upsert.assert_called_once()
        assert bulk_upsert.call_args.args[1] == "bom"

    @pytest.mark.asyncio
    async def test_empty_fetch_skips_upsert(self, monkeypatch):
        bulk_upsert = self._patch(monkeypatch, docs=[])
        await api_module._ingest_bom_historical(date(2026, 1, 1), date(2026, 1, 2))
        bulk_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_failure_skips_upsert(self, monkeypatch):
        bulk_upsert = self._patch(
            monkeypatch, docs=[{"station_id": "1", "ts": "t"}], validate_error=True
        )
        await api_module._ingest_bom_historical(date(2026, 1, 1), date(2026, 1, 2))
        bulk_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_mirrors_upserted_docs_into_duckdb(self, monkeypatch):
        docs = [{"station_id": "1", "ts": "t"}]
        self._patch(monkeypatch, docs=docs)
        await api_module._ingest_bom_historical(date(2026, 1, 1), date(2026, 1, 2))
        api_module.duckdb_store.write_historical.assert_called_once()
        call_args = api_module.duckdb_store.write_historical.call_args.args
        assert call_args[0] == "bom"
        assert call_args[1] == docs

    @pytest.mark.asyncio
    async def test_duckdb_failure_does_not_fail_the_job(self, monkeypatch):
        bulk_upsert = self._patch(monkeypatch, docs=[{"station_id": "1", "ts": "t"}])
        monkeypatch.setattr(
            api_module.duckdb_store,
            "write_historical",
            MagicMock(side_effect=RuntimeError("disk full")),
        )
        upserted = await api_module._ingest_bom_historical(
            date(2026, 1, 1), date(2026, 1, 2)
        )
        # The Mongo upsert (the job's actual success criterion) already
        # succeeded -- a DuckDB write failure must not raise out of the
        # ingest function or change its return value.
        bulk_upsert.assert_called_once()
        assert upserted == 1


class TestIngestAemoHistorical:
    def _patch(self, monkeypatch, *, docs_by_day):
        fake_fetcher = MagicMock()

        async def fetch_for_date(client, day):
            return docs_by_day.get(day, [])

        fake_fetcher.fetch_for_date = AsyncMock(side_effect=fetch_for_date)
        monkeypatch.setitem(
            api_module._AEMO_FETCHERS, "aemo_nem", MagicMock(return_value=fake_fetcher)
        )
        monkeypatch.setattr(api_module, "get_historical_db", lambda: object())
        bulk_upsert = AsyncMock(side_effect=lambda db, source, docs, run_id: len(docs))
        monkeypatch.setattr(api_module, "bulk_upsert", bulk_upsert)
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", MagicMock(return_value=0)
        )
        return bulk_upsert

    @pytest.mark.asyncio
    async def test_upserts_once_per_day_with_data(self, monkeypatch):
        d1, d3 = (
            date(2026, 1, 1),
            date(2026, 1, 3),
        )  # d2 (Jan 2) deliberately has no docs
        bulk_upsert = self._patch(
            monkeypatch,
            docs_by_day={
                d1: [{"region": "NSW1", "ts": "t1"}],
                d3: [{"region": "NSW1", "ts": "t3"}],
            },
        )
        await api_module._ingest_aemo_historical("aemo_nem", d1, d3)
        # d2 has no docs -> no upsert call for that day; d1 and d3 do.
        assert bulk_upsert.call_count == 2
        # ... and DuckDB gets mirrored once per successful day too, same as Mongo.
        assert api_module.duckdb_store.write_historical.call_count == 2
        assert (
            api_module.duckdb_store.write_historical.call_args_list[0].args[0]
            == "aemo_nem"
        )

    @pytest.mark.asyncio
    async def test_one_bad_day_does_not_abort_the_range(self, monkeypatch):
        d1, d2 = date(2026, 1, 1), date(2026, 1, 2)
        fake_fetcher = MagicMock()
        call_days = []

        async def fetch_for_date(client, day):
            call_days.append(day)
            if day == d1:
                raise RuntimeError("network blip")
            return [{"region": "NSW1", "ts": "t2"}]

        fake_fetcher.fetch_for_date = AsyncMock(side_effect=fetch_for_date)
        monkeypatch.setitem(
            api_module._AEMO_FETCHERS, "aemo_nem", MagicMock(return_value=fake_fetcher)
        )
        monkeypatch.setattr(api_module, "get_historical_db", lambda: object())
        bulk_upsert = AsyncMock(return_value=1)
        monkeypatch.setattr(api_module, "bulk_upsert", bulk_upsert)
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", MagicMock(return_value=0)
        )

        await api_module._ingest_aemo_historical("aemo_nem", d1, d2)

        assert call_days == [d1, d2]  # d2 still attempted after d1 failed
        bulk_upsert.assert_called_once()  # only for d2, which succeeded


class TestIngestOpenelectricityHistorical:
    def _patch(self, monkeypatch, *, docs, has_api_key=True, validate_error=False):
        fake_settings = MagicMock(
            oe_api_key="key" if has_api_key else None,
            oe_request_timeout_seconds=30,
        )
        monkeypatch.setattr(api_module, "get_settings", lambda: fake_settings)

        fake_fetcher = MagicMock()
        fake_fetcher.fetch = AsyncMock(return_value=docs)
        monkeypatch.setattr(
            api_module, "OpenElectricityFetcher", MagicMock(return_value=fake_fetcher)
        )
        monkeypatch.setattr(api_module, "get_historical_db", lambda: object())
        bulk_upsert = AsyncMock(return_value=len(docs))
        monkeypatch.setattr(api_module, "bulk_upsert", bulk_upsert)
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", MagicMock(return_value=0)
        )

        if validate_error:
            monkeypatch.setattr(
                api_module,
                "validate_openelectricity",
                MagicMock(side_effect=pandera.errors.SchemaError(None, None, "bad")),
            )
        else:
            monkeypatch.setattr(api_module, "validate_openelectricity", lambda d: d)
        return bulk_upsert

    @pytest.mark.asyncio
    async def test_happy_path_upserts(self, monkeypatch):
        bulk_upsert = self._patch(
            monkeypatch, docs=[{"network_code": "NEM", "ts": "t"}]
        )
        await api_module._ingest_openelectricity_historical(
            date(2026, 1, 1), date(2026, 1, 2)
        )
        bulk_upsert.assert_called_once()
        assert bulk_upsert.call_args.args[1] == "openelectricity"

    @pytest.mark.asyncio
    async def test_missing_api_key_skips_fetch_entirely(self, monkeypatch):
        bulk_upsert = self._patch(monkeypatch, docs=[], has_api_key=False)
        await api_module._ingest_openelectricity_historical(
            date(2026, 1, 1), date(2026, 1, 2)
        )
        bulk_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_failure_skips_upsert(self, monkeypatch):
        bulk_upsert = self._patch(
            monkeypatch, docs=[{"network_code": "NEM", "ts": "t"}], validate_error=True
        )
        await api_module._ingest_openelectricity_historical(
            date(2026, 1, 1), date(2026, 1, 2)
        )
        bulk_upsert.assert_not_called()


class TestIngestHolidaysHistorical:
    def _patch(self, monkeypatch, *, docs_by_year, validate_error=False):
        fake_fetcher = MagicMock()

        async def fetch(client, year):
            return docs_by_year.get(year, [])

        fake_fetcher.fetch = AsyncMock(side_effect=fetch)
        monkeypatch.setattr(
            api_module, "HolidayFetcher", MagicMock(return_value=fake_fetcher)
        )
        monkeypatch.setattr(api_module, "get_historical_db", lambda: object())
        bulk_upsert = AsyncMock(side_effect=lambda db, source, docs, run_id: len(docs))
        monkeypatch.setattr(api_module, "bulk_upsert", bulk_upsert)
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", MagicMock(return_value=0)
        )

        if validate_error:
            monkeypatch.setattr(
                api_module,
                "validate_holidays",
                MagicMock(side_effect=pandera.errors.SchemaError(None, None, "bad")),
            )
        else:
            monkeypatch.setattr(api_module, "validate_holidays", lambda d: d)
        return bulk_upsert

    @pytest.mark.asyncio
    async def test_upserts_once_per_year_spanned(self, monkeypatch):
        bulk_upsert = self._patch(
            monkeypatch,
            docs_by_year={
                2026: [{"region": "NSW", "date": "2026-01-01"}],
                2027: [{"region": "NSW", "date": "2027-01-01"}],
            },
        )
        await api_module._ingest_holidays_historical(date(2026, 6, 1), date(2027, 2, 1))
        assert bulk_upsert.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_year_skips_upsert(self, monkeypatch):
        bulk_upsert = self._patch(monkeypatch, docs_by_year={})
        await api_module._ingest_holidays_historical(
            date(2026, 1, 1), date(2026, 12, 31)
        )
        bulk_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_failure_skips_upsert(self, monkeypatch):
        bulk_upsert = self._patch(
            monkeypatch,
            docs_by_year={2026: [{"region": "NSW", "date": "2026-01-01"}]},
            validate_error=True,
        )
        await api_module._ingest_holidays_historical(
            date(2026, 1, 1), date(2026, 12, 31)
        )
        bulk_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_duckdb_write_uses_aemo_holidays_not_holidays(self, monkeypatch):
        # Regression: bulk_upsert is called with source="aemo_holidays"
        # (the Mongo collection key), not the API's "holidays" Source
        # literal -- the DuckDB write must use the same key, or it would
        # write/read against a table that MongoSettings.collection_for_source
        # doesn't recognize.
        self._patch(
            monkeypatch, docs_by_year={2026: [{"region": "NSW", "date": "2026-01-01"}]}
        )
        await api_module._ingest_holidays_historical(
            date(2026, 1, 1), date(2026, 12, 31)
        )
        api_module.duckdb_store.write_historical.assert_called_once()
        assert api_module.duckdb_store.write_historical.call_args.args[0] == (
            "aemo_holidays"
        )


class _FakeAsyncCursor:
    def __init__(self, docs):
        self._docs = docs

    def __aiter__(self):
        self._it = iter(self._docs)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration  # noqa: B904 - stdlib async iterator protocol


class _FakeCollection:
    def __init__(self, docs):
        self._docs = docs

    def find(self, filt, _projection):
        field = next(iter(filt))
        gte, lt = filt[field]["$gte"], filt[field]["$lt"]
        matched = [d for d in self._docs if gte <= d[field] < lt]
        return _FakeAsyncCursor(matched)


class _FakeDb(dict):
    def __getitem__(self, key):
        return dict.get(self, key, _FakeCollection([]))


class TestDailyCounts:
    def test_datetime_typed_field_bucketed_and_zero_filled(self, monkeypatch):
        # bom's `ts` is a real BSON datetime -- confirms the datetime
        # comparison branch and that a day with no docs still shows 0.
        docs = [
            {"ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)},
            {"ts": datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)},
            {"ts": datetime(2026, 1, 3, 0, 0, tzinfo=timezone.utc)},
        ]
        fake_db = _FakeDb({"bom_observations": _FakeCollection(docs)})
        monkeypatch.setattr(api_module, "get_historical_db", lambda: fake_db)

        import asyncio

        async def run():
            return await api_module._daily_counts(
                "bom", date(2026, 1, 1), date(2026, 1, 3), historical=True
            )

        counts = asyncio.run(run())
        assert counts == {
            date(2026, 1, 1): 2,
            date(2026, 1, 2): 0,
            date(2026, 1, 3): 1,
        }

    def test_string_typed_field_bucketed_correctly(self, monkeypatch):
        # holidays' `date` field is a plain ISO date string, not a BSON
        # datetime -- confirms the string-comparison branch.
        docs = [
            {"date": "2026-01-01"},
            {"date": "2026-01-01"},
            {"date": "2026-06-15"},
        ]
        fake_db = _FakeDb({"aemo_holidays": _FakeCollection(docs)})
        monkeypatch.setattr(api_module, "get_historical_db", lambda: fake_db)

        import asyncio

        async def run():
            return await api_module._daily_counts(
                "holidays", date(2026, 1, 1), date(2026, 6, 15), historical=True
            )

        counts = asyncio.run(run())
        assert counts[date(2026, 1, 1)] == 2
        assert counts[date(2026, 6, 15)] == 1
        assert counts[date(2026, 3, 1)] == 0  # a day with no docs in range

    def test_uses_live_db_when_historical_false(self, monkeypatch):
        live_db = _FakeDb(
            {
                "bom_observations": _FakeCollection(
                    [{"ts": datetime(2026, 1, 1, tzinfo=timezone.utc)}]
                )
            }
        )
        historical_db = _FakeDb({"bom_observations": _FakeCollection([])})
        monkeypatch.setattr(api_module, "get_db", lambda: live_db)
        monkeypatch.setattr(api_module, "get_historical_db", lambda: historical_db)

        import asyncio

        async def run():
            return await api_module._daily_counts(
                "bom", date(2026, 1, 1), date(2026, 1, 1), historical=False
            )

        counts = asyncio.run(run())
        assert counts[date(2026, 1, 1)] == 1


class TestRetryMissingDatesHelper:
    @pytest.mark.asyncio
    async def test_bom_retries_one_call_per_missing_day(self, monkeypatch):
        calls = []

        async def fake_bom(start, end, *, historical=True):
            calls.append((start, end, historical))
            return 5

        monkeypatch.setattr(api_module, "_ingest_bom_historical", fake_bom)
        total = await api_module._retry_missing_dates(
            "bom", [date(2026, 1, 1), date(2026, 1, 3)], historical=True
        )
        assert total == 10
        assert calls == [
            (date(2026, 1, 1), date(2026, 1, 1), True),
            (date(2026, 1, 3), date(2026, 1, 3), True),
        ]

    @pytest.mark.asyncio
    async def test_holidays_dedupes_to_one_call_per_distinct_year(self, monkeypatch):
        calls = []

        async def fake_holidays(start, end, *, historical=True):
            calls.append((start, end, historical))
            return 3

        monkeypatch.setattr(api_module, "_ingest_holidays_historical", fake_holidays)
        # Three missing days, but only two distinct years.
        total = await api_module._retry_missing_dates(
            "holidays",
            [date(2026, 1, 1), date(2026, 6, 1), date(2027, 3, 1)],
            historical=False,
        )
        assert total == 6
        assert calls == [
            (date(2026, 1, 1), date(2026, 12, 31), False),
            (date(2027, 1, 1), date(2027, 12, 31), False),
        ]

    @pytest.mark.asyncio
    async def test_aemo_passes_source_through(self, monkeypatch):
        calls = []

        async def fake_aemo(source, start, end, *, historical=True):
            calls.append((source, start, end, historical))
            return 1

        monkeypatch.setattr(api_module, "_ingest_aemo_historical", fake_aemo)
        await api_module._retry_missing_dates(
            "aemo_wem", [date(2026, 1, 1)], historical=True
        )
        assert calls == [("aemo_wem", date(2026, 1, 1), date(2026, 1, 1), True)]


class TestGetDailyCountsEndpoint:
    def test_returns_counts_over_requested_range(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end, *, historical):
            return {date(2026, 1, 1): 48, date(2026, 1, 2): 0}

        monkeypatch.setattr(api_module, "_daily_counts", fake_daily_counts)
        response = client.get(
            "/ingestion/daily-counts",
            params={
                "source": "bom",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["source"] == "bom"
        assert body["historical"] is False
        assert body["counts"] == [
            {"date": "2026-01-01", "count": 48},
            {"date": "2026-01-02", "count": 0},
        ]

    def test_historical_without_config_503s(self, client):
        response = client.get(
            "/ingestion/daily-counts",
            params={"source": "bom", "date": "2026-01-01", "historical": "true"},
        )
        assert response.status_code == 503

    def test_invalid_date_selection_422s(self, client):
        response = client.get("/ingestion/daily-counts", params={"source": "bom"})
        assert response.status_code == 422


class TestTriggerRetryMissingEndpoint:
    def test_no_gaps_found_returns_without_a_job(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end, *, historical):
            return {date(2026, 1, 1): 48, date(2026, 1, 2): 48}

        monkeypatch.setattr(api_module, "_daily_counts", fake_daily_counts)
        response = client.post(
            "/ingestion/retry-missing",
            params={
                "source": "bom",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "no_gaps_found"
        assert body["missing_dates"] == []
        assert "job_id" not in body

    def test_gaps_found_schedules_a_job(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end, *, historical):
            return {date(2026, 1, 1): 48, date(2026, 1, 2): 0}

        retry_calls = []

        async def fake_retry(source, missing_dates, *, historical):
            retry_calls.append((source, missing_dates, historical))
            return 48

        monkeypatch.setattr(api_module, "_daily_counts", fake_daily_counts)
        monkeypatch.setattr(api_module, "_retry_missing_dates", fake_retry)
        response = client.post(
            "/ingestion/retry-missing",
            params={
                "source": "bom",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "started"
        assert body["missing_dates"] == ["2026-01-02"]
        assert isinstance(body["job_id"], str)
        assert retry_calls == [("bom", [date(2026, 1, 2)], False)]

    def test_min_expected_count_also_flags_partial_days(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end, *, historical):
            return {date(2026, 1, 1): 48, date(2026, 1, 2): 10}  # 10 < threshold

        async def fake_retry(source, missing_dates, *, historical):
            return 0

        monkeypatch.setattr(api_module, "_daily_counts", fake_daily_counts)
        monkeypatch.setattr(api_module, "_retry_missing_dates", fake_retry)
        response = client.post(
            "/ingestion/retry-missing",
            params={
                "source": "bom",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "min_expected_count": 40,
            },
        )
        body = response.json()
        assert body["missing_dates"] == ["2026-01-02"]

    def test_poll_completed_reports_upserted_total(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end, *, historical):
            return {date(2026, 1, 1): 0}

        async def fake_retry(source, missing_dates, *, historical):
            return 48

        monkeypatch.setattr(api_module, "_daily_counts", fake_daily_counts)
        monkeypatch.setattr(api_module, "_retry_missing_dates", fake_retry)
        trigger = client.post(
            "/ingestion/retry-missing",
            params={"source": "bom", "date": "2026-01-01"},
        )
        job_id = trigger.json()["job_id"]

        status = client.get(f"/ingestion/retry-missing/{job_id}")
        assert status.status_code == 200
        body = status.json()
        assert body["status"] == "completed"
        assert body["upserted"] == 48

    def test_poll_unknown_job_id_404s(self, client):
        response = client.get("/ingestion/retry-missing/no-such-job")
        assert response.status_code == 404

    def test_historical_without_config_503s(self, client):
        response = client.post(
            "/ingestion/retry-missing",
            params={"source": "bom", "date": "2026-01-01", "historical": "true"},
        )
        assert response.status_code == 503
