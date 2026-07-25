"""Tests for ecolens.ingestion.api (the /ingestion/historical endpoint).

Three layers:
  * `Test*` classes down to `TestJobStatusPolling` exercise the router:
    each `_ingest_*_historical` job function is monkeypatched to a spy
    (they fire real HTTP fetches, out of scope here), so these verify
    request validation and that the right job gets scheduled with the
    right (possibly normalized) date range. Same pattern as
    test_forecasting_api.py.
  * `TestIngest*Historical` classes test each job function's own body
    directly (fetch -> validate -> write), with the fetcher class,
    validator, and `duckdb_store.write_historical` all monkeypatched --
    still no real HTTP, just one layer deeper than the router tests
    above.
  * `TestDailyCounts` writes real rows into a tmp_path-scoped DuckDB
    file (via `duckdb_store.write_historical`) and exercises the actual
    `count_by_day` SQL read path -- day-bucketing is exactly the kind
    of logic worth testing against the real engine rather than a mock.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pandera.errors
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ecolens.config import get_settings
from ecolens.ingestion import api as api_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HISTORICAL_DUCKDB_PATH", str(tmp_path / "historical.duckdb"))
    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(api_module.router)
    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_jobs():
    api_module._jobs.clear()
    yield
    api_module._jobs.clear()


class TestRequestValidation:
    def test_date_and_range_together_422s(self, client):
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

    def test_neither_date_nor_range_422s(self, client):
        response = client.post("/ingestion/historical", params={"source": "bom"})
        assert response.status_code == 422

    def test_range_missing_end_date_422s(self, client):
        response = client.post(
            "/ingestion/historical",
            params={"source": "bom", "start_date": "2026-01-01"},
        )
        assert response.status_code == 422

    def test_end_before_start_422s(self, client):
        response = client.post(
            "/ingestion/historical",
            params={
                "source": "bom",
                "start_date": "2026-01-05",
                "end_date": "2026-01-01",
            },
        )
        assert response.status_code == 422

    def test_unknown_source_422s(self, client):
        response = client.post(
            "/ingestion/historical",
            params={"source": "not_a_real_source", "date": "2026-01-01"},
        )
        assert response.status_code == 422


class TestDispatch:
    def test_single_date_normalizes_to_a_one_day_range(self, client, monkeypatch):
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

    def test_range_dispatches_with_start_and_end(self, client, monkeypatch):
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
    def test_aemo_sources_dispatch_with_source_name(self, client, monkeypatch, source):
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

    def test_openelectricity_dispatches(self, client, monkeypatch):
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

    def test_holidays_dispatches(self, client, monkeypatch):
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
    def test_completed_job_reports_written_count(self, client, monkeypatch):
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
        assert body["written"] == 7
        assert body["error"] is None
        assert body["finished_at"] is not None

    def test_failed_job_reports_error(self, client, monkeypatch):
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
        assert body["written"] is None

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
        write_historical = MagicMock(return_value=len(docs))
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", write_historical
        )

        if validate_error:
            monkeypatch.setattr(
                api_module,
                "validate_bom",
                MagicMock(side_effect=pandera.errors.SchemaError(None, None, "bad")),
            )
        else:
            monkeypatch.setattr(api_module, "validate_bom", lambda d: d)
        return write_historical

    @pytest.mark.asyncio
    async def test_happy_path_writes_to_duckdb(self, monkeypatch):
        docs = [{"station_id": "1", "ts": "t"}]
        write_historical = self._patch(monkeypatch, docs=docs)
        written = await api_module._ingest_bom_historical(
            date(2026, 1, 1), date(2026, 1, 2)
        )
        write_historical.assert_called_once()
        assert write_historical.call_args.args[0] == "bom"
        assert write_historical.call_args.args[1] == docs
        assert written == len(docs)

    @pytest.mark.asyncio
    async def test_empty_fetch_skips_write(self, monkeypatch):
        write_historical = self._patch(monkeypatch, docs=[])
        await api_module._ingest_bom_historical(date(2026, 1, 1), date(2026, 1, 2))
        write_historical.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_failure_skips_write(self, monkeypatch):
        write_historical = self._patch(
            monkeypatch, docs=[{"station_id": "1", "ts": "t"}], validate_error=True
        )
        await api_module._ingest_bom_historical(date(2026, 1, 1), date(2026, 1, 2))
        write_historical.assert_not_called()

    @pytest.mark.asyncio
    async def test_write_failure_propagates(self, monkeypatch):
        # Unlike the day/year-looping sources, a single-shot ingest like
        # bom has no per-day granularity to skip -- DuckDB is the sole
        # store now, so a write failure here is a real job failure, not
        # something to swallow.
        self._patch(monkeypatch, docs=[{"station_id": "1", "ts": "t"}])
        monkeypatch.setattr(
            api_module.duckdb_store,
            "write_historical",
            MagicMock(side_effect=RuntimeError("disk full")),
        )
        with pytest.raises(RuntimeError, match="disk full"):
            await api_module._ingest_bom_historical(date(2026, 1, 1), date(2026, 1, 2))


class TestIngestAemoHistorical:
    def _patch(self, monkeypatch, *, docs_by_day):
        fake_fetcher = MagicMock()

        async def fetch_for_date(client, day):
            return docs_by_day.get(day, [])

        fake_fetcher.fetch_for_date = AsyncMock(side_effect=fetch_for_date)
        monkeypatch.setitem(
            api_module._AEMO_FETCHERS, "aemo_nem", MagicMock(return_value=fake_fetcher)
        )
        write_historical = MagicMock(side_effect=lambda source, docs, **kw: len(docs))
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", write_historical
        )
        return write_historical

    @pytest.mark.asyncio
    async def test_writes_once_per_day_with_data(self, monkeypatch):
        d1, d3 = (
            date(2026, 1, 1),
            date(2026, 1, 3),
        )  # d2 (Jan 2) deliberately has no docs
        write_historical = self._patch(
            monkeypatch,
            docs_by_day={
                d1: [{"region": "NSW1", "ts": "t1"}],
                d3: [{"region": "NSW1", "ts": "t3"}],
            },
        )
        written_total = await api_module._ingest_aemo_historical("aemo_nem", d1, d3)
        # d2 has no docs -> no write call for that day; d1 and d3 do.
        assert write_historical.call_count == 2
        assert write_historical.call_args_list[0].args[0] == "aemo_nem"
        assert written_total == 2

    @pytest.mark.asyncio
    async def test_one_bad_day_fetch_does_not_abort_the_range(self, monkeypatch):
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
        write_historical = MagicMock(return_value=1)
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", write_historical
        )

        await api_module._ingest_aemo_historical("aemo_nem", d1, d2)

        assert call_days == [d1, d2]  # d2 still attempted after d1 failed
        write_historical.assert_called_once()  # only for d2, which succeeded

    @pytest.mark.asyncio
    async def test_one_bad_days_write_does_not_abort_the_range(self, monkeypatch):
        # Regression: a single day's DuckDB write failure (e.g. a lock
        # conflict that outlasted write_historical's own internal
        # retries) used to be able to propagate straight out of this
        # function, aborting every remaining day and losing
        # written_total entirely -- even though fetch failures were
        # already protected the same way.
        d1, d3 = date(2026, 1, 1), date(2026, 1, 3)  # d2 (Jan 2) is the flaky day
        fake_fetcher = MagicMock()
        fake_fetcher.fetch_for_date = AsyncMock(
            return_value=[{"region": "NSW1", "ts": "t"}]
        )
        monkeypatch.setitem(
            api_module._AEMO_FETCHERS, "aemo_nem", MagicMock(return_value=fake_fetcher)
        )

        call_count = {"n": 0}

        def flaky_write(source, docs, **kw):
            call_count["n"] += 1
            if call_count["n"] == 2:  # d2's write times out
                raise TimeoutError("lock conflict")
            return len(docs)

        monkeypatch.setattr(api_module.duckdb_store, "write_historical", flaky_write)

        written_total = await api_module._ingest_aemo_historical("aemo_nem", d1, d3)

        # d1 and d3 succeeded (1 doc each); d2's write failure was
        # skipped, not fatal -- the function still returns a real total
        # instead of raising and losing everything.
        assert written_total == 2


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
        write_historical = MagicMock(return_value=len(docs))
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", write_historical
        )

        if validate_error:
            monkeypatch.setattr(
                api_module,
                "validate_openelectricity",
                MagicMock(side_effect=pandera.errors.SchemaError(None, None, "bad")),
            )
        else:
            monkeypatch.setattr(api_module, "validate_openelectricity", lambda d: d)
        return write_historical

    @pytest.mark.asyncio
    async def test_happy_path_writes(self, monkeypatch):
        write_historical = self._patch(
            monkeypatch, docs=[{"network_code": "NEM", "ts": "t"}]
        )
        await api_module._ingest_openelectricity_historical(
            date(2026, 1, 1), date(2026, 1, 2)
        )
        write_historical.assert_called_once()
        assert write_historical.call_args.args[0] == "openelectricity"

    @pytest.mark.asyncio
    async def test_missing_api_key_skips_fetch_entirely(self, monkeypatch):
        write_historical = self._patch(monkeypatch, docs=[], has_api_key=False)
        await api_module._ingest_openelectricity_historical(
            date(2026, 1, 1), date(2026, 1, 2)
        )
        write_historical.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_failure_skips_write(self, monkeypatch):
        write_historical = self._patch(
            monkeypatch, docs=[{"network_code": "NEM", "ts": "t"}], validate_error=True
        )
        await api_module._ingest_openelectricity_historical(
            date(2026, 1, 1), date(2026, 1, 2)
        )
        write_historical.assert_not_called()


class TestIngestHolidaysHistorical:
    def _patch(self, monkeypatch, *, docs_by_year, validate_error=False):
        fake_fetcher = MagicMock()

        async def fetch(client, year):
            return docs_by_year.get(year, [])

        fake_fetcher.fetch = AsyncMock(side_effect=fetch)
        monkeypatch.setattr(
            api_module, "HolidayFetcher", MagicMock(return_value=fake_fetcher)
        )
        write_historical = MagicMock(side_effect=lambda source, docs, **kw: len(docs))
        monkeypatch.setattr(
            api_module.duckdb_store, "write_historical", write_historical
        )

        if validate_error:
            monkeypatch.setattr(
                api_module,
                "validate_holidays",
                MagicMock(side_effect=pandera.errors.SchemaError(None, None, "bad")),
            )
        else:
            monkeypatch.setattr(api_module, "validate_holidays", lambda d: d)
        return write_historical

    @pytest.mark.asyncio
    async def test_writes_once_per_year_spanned(self, monkeypatch):
        write_historical = self._patch(
            monkeypatch,
            docs_by_year={
                2026: [{"region": "NSW", "date": "2026-01-01"}],
                2027: [{"region": "NSW", "date": "2027-01-01"}],
            },
        )
        await api_module._ingest_holidays_historical(date(2026, 6, 1), date(2027, 2, 1))
        assert write_historical.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_year_skips_write(self, monkeypatch):
        write_historical = self._patch(monkeypatch, docs_by_year={})
        await api_module._ingest_holidays_historical(
            date(2026, 1, 1), date(2026, 12, 31)
        )
        write_historical.assert_not_called()

    @pytest.mark.asyncio
    async def test_validation_failure_skips_write(self, monkeypatch):
        write_historical = self._patch(
            monkeypatch,
            docs_by_year={2026: [{"region": "NSW", "date": "2026-01-01"}]},
            validate_error=True,
        )
        await api_module._ingest_holidays_historical(
            date(2026, 1, 1), date(2026, 12, 31)
        )
        write_historical.assert_not_called()

    @pytest.mark.asyncio
    async def test_duckdb_write_uses_aemo_holidays_not_holidays(self, monkeypatch):
        # Regression: the write must use source="aemo_holidays" (the
        # table key), not the API's "holidays" Source literal -- passing
        # "holidays" would hit IngestionSettings.table_for_source's
        # KeyError, since "holidays" isn't itself a recognized source key.
        write_historical = self._patch(
            monkeypatch, docs_by_year={2026: [{"region": "NSW", "date": "2026-01-01"}]}
        )
        await api_module._ingest_holidays_historical(
            date(2026, 1, 1), date(2026, 12, 31)
        )
        write_historical.assert_called_once()
        assert write_historical.call_args.args[0] == "aemo_holidays"

    @pytest.mark.asyncio
    async def test_one_bad_years_write_does_not_abort_the_range(self, monkeypatch):
        # Same regression as TestIngestAemoHistorical's equivalent test.
        fake_fetcher = MagicMock()

        async def fetch(client, year):
            return [{"region": "NSW", "date": f"{year}-01-01"}]

        fake_fetcher.fetch = AsyncMock(side_effect=fetch)
        monkeypatch.setattr(
            api_module, "HolidayFetcher", MagicMock(return_value=fake_fetcher)
        )
        monkeypatch.setattr(api_module, "validate_holidays", lambda d: d)

        call_count = {"n": 0}

        def flaky_write(source, docs, **kw):
            call_count["n"] += 1
            if call_count["n"] == 2:  # 2027's write times out
                raise TimeoutError("lock conflict")
            return len(docs)

        monkeypatch.setattr(api_module.duckdb_store, "write_historical", flaky_write)

        written_total = await api_module._ingest_holidays_historical(
            date(2026, 1, 1), date(2028, 12, 31)
        )

        # 2026 and 2028 succeeded (1 doc each); 2027's write failure was
        # skipped, not fatal.
        assert written_total == 2


class TestDailyCounts:
    """Writes real rows via duckdb_store.write_historical and exercises
    the real count_by_day SQL path -- see the `client` fixture for the
    per-test tmp_path DuckDB isolation.
    """

    def test_datetime_typed_field_bucketed_and_zero_filled(self, client):
        from ecolens.ingestion.storage.duckdb_store import write_historical

        write_historical(
            "bom",
            [
                {
                    "station_id": "1",
                    "ts": datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc),
                },
                {
                    "station_id": "1",
                    "ts": datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc),
                },
                {
                    "station_id": "1",
                    "ts": datetime(2026, 1, 3, 0, 0, tzinfo=timezone.utc),
                },
            ],
        )

        import asyncio

        counts = asyncio.run(
            api_module._daily_counts("bom", date(2026, 1, 1), date(2026, 1, 3))
        )
        assert counts == {
            date(2026, 1, 1): 2,
            date(2026, 1, 2): 0,
            date(2026, 1, 3): 1,
        }

    def test_string_typed_date_field_bucketed_correctly(self, client):
        # holidays' `date` field lands as a plain ISO string (not a
        # native temporal type) -- confirms count_by_day's CAST handles
        # it the same as a native column.
        from ecolens.ingestion.storage.duckdb_store import write_historical

        write_historical(
            "aemo_holidays",
            [
                {"region": "NSW1", "date": "2026-01-01"},
                {"region": "QLD1", "date": "2026-01-01"},
                {"region": "NSW1", "date": "2026-06-15"},
            ],
        )

        import asyncio

        counts = asyncio.run(
            api_module._daily_counts("holidays", date(2026, 1, 1), date(2026, 6, 15))
        )
        assert counts[date(2026, 1, 1)] == 2
        assert counts[date(2026, 6, 15)] == 1
        assert counts[date(2026, 3, 1)] == 0  # a day with no rows in range

    def test_never_ingested_source_is_all_zero(self, client):
        import asyncio

        counts = asyncio.run(
            api_module._daily_counts("bom", date(2026, 1, 1), date(2026, 1, 2))
        )
        assert counts == {date(2026, 1, 1): 0, date(2026, 1, 2): 0}


class TestRetryMissingDatesHelper:
    @pytest.mark.asyncio
    async def test_bom_retries_one_call_per_missing_day(self, monkeypatch):
        calls = []

        async def fake_bom(start, end):
            calls.append((start, end))
            return 5

        monkeypatch.setattr(api_module, "_ingest_bom_historical", fake_bom)
        total = await api_module._retry_missing_dates(
            "bom", [date(2026, 1, 1), date(2026, 1, 3)]
        )
        assert total == 10
        assert calls == [
            (date(2026, 1, 1), date(2026, 1, 1)),
            (date(2026, 1, 3), date(2026, 1, 3)),
        ]

    @pytest.mark.asyncio
    async def test_holidays_dedupes_to_one_call_per_distinct_year(self, monkeypatch):
        calls = []

        async def fake_holidays(start, end):
            calls.append((start, end))
            return 3

        monkeypatch.setattr(api_module, "_ingest_holidays_historical", fake_holidays)
        # Three missing days, but only two distinct years.
        total = await api_module._retry_missing_dates(
            "holidays", [date(2026, 1, 1), date(2026, 6, 1), date(2027, 3, 1)]
        )
        assert total == 6
        assert calls == [
            (date(2026, 1, 1), date(2026, 12, 31)),
            (date(2027, 1, 1), date(2027, 12, 31)),
        ]

    @pytest.mark.asyncio
    async def test_aemo_passes_source_through(self, monkeypatch):
        calls = []

        async def fake_aemo(source, start, end):
            calls.append((source, start, end))
            return 1

        monkeypatch.setattr(api_module, "_ingest_aemo_historical", fake_aemo)
        await api_module._retry_missing_dates("aemo_wem", [date(2026, 1, 1)])
        assert calls == [("aemo_wem", date(2026, 1, 1), date(2026, 1, 1))]


class TestGetDailyCountsEndpoint:
    def test_returns_counts_over_requested_range(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end):
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
        assert body["counts"] == [
            {"date": "2026-01-01", "count": 48},
            {"date": "2026-01-02", "count": 0},
        ]

    def test_invalid_date_selection_422s(self, client):
        response = client.get("/ingestion/daily-counts", params={"source": "bom"})
        assert response.status_code == 422


class TestTriggerRetryMissingEndpoint:
    def test_no_gaps_found_returns_without_a_job(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end):
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
        async def fake_daily_counts(source, start, end):
            return {date(2026, 1, 1): 48, date(2026, 1, 2): 0}

        retry_calls = []

        async def fake_retry(source, missing_dates):
            retry_calls.append((source, missing_dates))
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
        assert retry_calls == [("bom", [date(2026, 1, 2)])]

    def test_min_expected_count_also_flags_partial_days(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end):
            return {date(2026, 1, 1): 48, date(2026, 1, 2): 10}  # 10 < threshold

        async def fake_retry(source, missing_dates):
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

    def test_poll_completed_reports_written_total(self, client, monkeypatch):
        async def fake_daily_counts(source, start, end):
            return {date(2026, 1, 1): 0}

        async def fake_retry(source, missing_dates):
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
        assert body["written"] == 48

    def test_poll_unknown_job_id_404s(self, client):
        response = client.get("/ingestion/retry-missing/no-such-job")
        assert response.status_code == 404
