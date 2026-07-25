# EcoLens Project TODOs

Rebuilt from scratch on 2026-07-22 to reflect what's *actually* remaining,
verified against the real source tree (not assumed from service READMEs,
which oversell finished state in places — see the Dashboard section).
Completed work has been dropped; see git history / each service's own
`TODO.md` for what already landed.

---

## 🚨 Priority (Immediate)
- [ ] [ECO-140] **Commit the uncommitted backlog.** Last real commit is 2026-07-20; the working tree currently has 49 untracked files, 36 modified, 12 git thinks are deleted — including all of `services/forecast-api`'s actual source (`pyproject.toml` is empty at HEAD) and most of `services/data-pipeline/src/ecolens/forecasting/`. Real data-loss risk until this lands.
- [ ] [ECO-122] **Get the LSTM to a genuinely deployable MAPE.** Current registered versions have run 37–66% MAPE depending on the training run — none of that is production-quality. `hyperparameter_search.yml` (Optuna search space, ECO-113) is wired up and ready; a real multi-trial search just hasn't been run to completion yet (long unattended runs don't survive in this dev environment — run `make model-tune N_TRIALS=<n>` detached, then apply `best_params` and retrain).

---

## 📊 Service: Data Pipeline
- [ ] [ECO-102] **Universal Fetcher base class.** Still five independent per-source fetcher classes (AEMO NEM/WEM, BoM, OpenElectricity, holidays) with no shared template — ECO-101's circuit breaker is a step toward consistency but doesn't unify the fetch/log pattern itself.
- [ ] [ECO-104] **OpenElectricity response cache.** Connector itself works (`openelectricity/engine.py`, `client.py`), but there's still no 60-second cache/TTL anywhere in that source's files.
- [ ] [ECO-106] **Fallback tiers for AEMO NEM/WEM + OpenElectricity.** Only `bom` and `holidays` have the tiered live → cache → synthetic pattern; the other three sources have no fallback at all if the live call fails.
- [ ] [ECO-120] **Resolve the empty `shared/` stubs.** `shared/config.py` (duplicate of the real `config.py`, unused — probably just delete it), `shared/db/session.py`, `shared/observability/metrics.py`, `ingestion/api.py`, and `ingestion/validators/aemo.py` are all still 0-line files.
- [ ] [ECO-121] **Wire up `docker-compose.yml`.** It's empty; the real postgres/redis/minio/mlflow/prefect/api/web/prometheus/grafana/loki service definitions live in `docker-compose copy.yml` instead, unused. `make up`/`make down` don't currently do anything.

### 🗄 MongoDB fully removed — DuckDB is now the sole raw store (ECO-150..159)
ECO-150..157 below originally proposed DuckDB as a *cold-storage backup*
sitting alongside a live MongoDB cluster (`ArchiveManager.archive()` would
delete old Mongo docs after confirming they were backed up to DuckDB
first). That whole premise is gone: MongoDB has been removed from the
ingestion pipeline entirely — DuckDB (`ingestion/storage/duckdb_store.py`)
is now the *only* raw store, written to directly by every live fetcher's
trigger script and by `ingestion/api.py`'s `/ingestion/historical` /
`/ingestion/retry-missing` endpoints. `ArchiveManager.archive()` is now a
documented no-op (nothing to archive away from), and `RawSyncer`
(`ingestion/storage/postgres.py`) reads from DuckDB instead of Mongo to
populate Postgres `raw.*`, which dbt still builds from unchanged.
- [✓] [ECO-158] **DuckDB historical store landed** (`duckdb_store.py`:
  `write_historical()`/`read_historical()`/`read_historical_since()`/
  `latest_fetched_at()`/`count_by_day()`), covered by
  `tests/test_ingestion_storage_duckdb.py`.
- [✓] [ECO-159] **Full MongoDB removal**, replacing ECO-150..157's
  cold-storage-backup design now that there's no live Mongo cluster left
  to archive from:
  - `ingestion/storage/settings.py`: `MongoSettings` → `IngestionSettings`
    (dropped all Mongo connection/pool/retry/write-concern fields; kept
    `table_for_source()`/`unique_key_for_source()` and the `ingest_*`
    concurrency/retry tunables, which were never actually Mongo-specific).
  - `ingestion/storage/mongo.py` deleted (`bulk_upsert`/`get_db`/
    `get_historical_db`/`get_mongo_client`).
  - `ingestion/storage/postgres.py` (`RawSyncer`): reads DuckDB via the
    new `duckdb_store.read_historical_since()` instead of a Mongo cursor.
  - `ingestion/api.py`: the live/historical dual-Mongo-cluster split (the
    `historical: bool` param, `MONGO_URI_HISTORICAL` 503 checks) is gone
    — one store, one code path. `_daily_counts()` is now a real SQL
    `GROUP BY` (`duckdb_store.count_by_day()`) instead of a Python-side
    Mongo-cursor bucketing workaround. Per-day/year write failures inside
    the `_ingest_aemo_historical`/`_ingest_holidays_historical` loops are
    still caught and skipped (not fatal to the whole range) — same
    resilience property as before, just guarding a DuckDB write now
    instead of a Mongo one.
  - `warehouse/runner/archive.py` (`ArchiveManager.archive()`): now a
    documented no-op. `warehouse/runner/freshness.py`
    (`SourceFreshnessChecker`): reads each source's
    `duckdb_store.latest_fetched_at()` instead of a Mongo `find_one`.
  - 5 `scripts/trigger_ingest_*.py` + `backfill_bom_historical.py`:
    write via `duckdb_store.write_historical()`/`fetcher.write_duckdb()`
    directly, no more parallel Mongo write.
  - `motor`/`pymongo` removed from `pyproject.toml`; duplicate `mongo_uri`/
    `mongo_db_name` fields removed from the global `Settings` (config.py)
    — dead config only `scripts/test_mongo_connection.py` used, which is
    now deleted (nothing left to smoke-test).
  - **Real bug caught while writing real-data tests for this**:
    `count_by_day()`'s `GROUP BY` originally cast the bucketing key to
    `TIMESTAMP` instead of `DATE`, so two rows on the same calendar day
    at different times landed in separate groups — every real day with
    more than one distinct timestamp (i.e. every real day) was
    undercounted. Would have made `/ingestion/retry-missing` think
    almost every already-complete day was missing/partial. Fixed before
    this ever shipped.
  - Tests: `test_mongo_storage.py` deleted; `test_ingestion_api.py`,
    `test_warehouse_runner_archive.py`, `test_warehouse_runner_freshness.py`
    rewritten (the latter two now seed/assert against a real tmp_path
    DuckDB file instead of Mongo mocks); `conftest.py`'s
    `FakeMongoClient`/`FakeMongoCollection` doubles removed;
    `test_circuit_breaker.py`/`test_aemo_wem_client.py`/
    `test_holidays_client.py`/`test_openelectricity_client.py`/
    `test_config.py` updated for the settings rename. Full suite green.
  - **Docs**: `ingestion/INGESTION.md` and `warehouse/werehouse.md` have
    both been rewritten for the DuckDB-based design (not a mechanical
    find/replace — new "why DuckDB" framing, the single-writer-lock
    caveat, updated code samples matching the real `duckdb_store`/
    `RawSyncer` APIs). The root `CLAUDE.md` still has some Mongo-era
    framing left — see ECO-160.
- [ ] [ECO-160] **Update `CLAUDE.md`'s remaining Mongo-era framing.**
  The root project-instructions file still describes parts of the
  ingestion layer in terms of the pre-ECO-159 MongoDB design in a few
  places. Lower priority than the two docs above (this one's read by an
  AI agent, not shipped as user-facing documentation), but worth a pass.
- [ ] [ECO-161] **`.github/workflows/ingest.yml` doesn't persist
  DuckDB data across runs.** With Mongo, `MONGO_URI` pointed at a real
  remote Atlas cluster, so every scheduled run accumulated real history.
  `historical_duckdb_path` is now a local file on the GitHub Actions
  runner, discarded when the job ends — the workflow currently ingests
  and immediately throws the data away. Needs a restore-before/
  upload-after step (`actions/cache`, `actions/upload-artifact` +
  download, or an S3 sync) before this workflow actually accumulates
  anything.

---

## 🏗 Service: Forecast API
- [ ] [ECO-F10] **Fix `services/forecast-api/TODO.md` itself.** It still lists ECO-F02–F09, ECO-T01, and ECO-T04 as backlog/not-started — they're actually implemented and covered by real tests (model loader, hot-reload, rollback, quantization, conformal-band serving, MLflow registry integration tests). Pure doc debt, but worth fixing so the file stops reading as "model-serving hasn't started."
- [ ] [ECO-P02] **Tune the asyncpg pool** (`pg_min_pool`/`pg_max_pool`/`pg_command_timeout_seconds`) against real `/v1/forecast` traffic — current values are unvalidated defaults.
- [ ] [ECO-P03] **Run the CPU inference optimization benchmark.** `scripts/benchmark_inference.py` exists (quantized vs fp32, latency + RSS) but has never actually been run to decide whether `FORECAST_INFERENCE_OPTIMIZATION=dynamic_quantization` is worth enabling for this model's size.
- [ ] [ECO-F09] **Revisit `model_reload_interval_seconds`** once real online-learning/fine-tune cadence from `data-pipeline` is observed in practice — currently just the 60s default, never re-evaluated against actual promotion frequency.

---

## 🖥 Service: Dashboard
- [✓] [ECO-13X] **Blocking prerequisite found and fixed:** `src/lib/{data,utils,animations,gsap}.ts` — imported by every single page/component in the app — didn't exist anywhere in git history despite the "707-line mock object" description below. The dashboard could not `typecheck`/`lint`/`build` at all before this. Reconstructed all four modules (driven by `tests/unit/*.test.ts`'s assertions + actual per-page field usage, verified via the TS compiler iteratively) plus fixed several genuine pre-existing bugs surfaced once tooling actually ran: a `whileHover`/`Variants` type misuse in `solutions/page.tsx`, a render-time mutation in `charts.tsx`'s donut-chart offset calc, an anonymous default export in `tailwind.config.ts`, 3 unescaped-entity JSX errors, and `next lint` itself being a dead command in Next 16 (no ESLint config ever existed — added `eslint.config.mjs` + pinned `eslint@^9`, since `eslint-plugin-react` doesn't yet support ESLint 10). Verified: `pnpm typecheck`/`pnpm lint` (0 errors)/`pnpm test` (68/68)/`pnpm build` (33/33 static pages, `out/` confirmed) all genuinely pass.
- [✓] [ECO-130] **Wire real API integration.** Added `src/lib/api-client.ts` (typed fetch client, `NEXT_PUBLIC_FORECAST_API_BASE`/`NEXT_PUBLIC_WAREHOUSE_API_BASE` env vars, `.env.example` added) + `src/lib/hooks.ts` (React Query wrappers). Wired a genuinely-live `<LiveForecastCard>` (region selector, real `GET /v1/forecast/{region}`, loading/error states, graceful "backend unavailable" fallback instead of a crash) into `/dashboard/home` and `/dashboard/analytics`. The other ~30 pages still read `src/lib/data.ts`'s static/demo dataset — not converted, per the original scope ("you don't need to convert all 32 pages").
- [✓] [ECO-131] **Implement authentication.** `src/lib/auth.tsx`: a demo/local `AuthProvider` (localStorage-backed session, explicitly documented in-file as NOT real auth — no backend, no password check, no hashing — since no auth service exists anywhere in this stack to integrate with). Login/signup forms split into real client components (`login-form.tsx`/`signup-form.tsx`) with actual `onSubmit`, validation (password match, min length, terms-agreement), loading/error states, and redirect into `/dashboard/home` (or `/onboarding`) on success. Structured so a real backend swap later is a 3-function change (`login`/`signup`/`logout`), not a rewrite.
- [✓] [ECO-132] **Add a real data-fetching/state layer.** `@tanstack/react-query` installed, `QueryProvider` (lazily-constructed `QueryClient`, 1 retry, no refetch-on-focus since the backend may not be running) wired at the app root in `layout.tsx`, used by `useForecast`/`useForecastApiHealth` in `hooks.ts`.
- [✓] [ECO-133] **Add dashboard to CI.** New `dashboard` job in `.github/workflows/main.yml` (separate from `lint-and-test`, pnpm/Node setup, typecheck + lint + test + build) — verified the exact same commands pass locally first.

---

## 🔧 Cross-Service / Infrastructure
- [ ] [ECO-141] **Fix `.github/workflows/ingest.yml`'s cron/comment mismatch.** Comment says "every 15 minutes"; the actual cron expression is `*/30 * * * *` (every 30 minutes).

---

<!-- *Legend: [ECO-XXX] refers to GitHub Issue ID. Run `make list-todos` to print all tagged TODOs across every service, `make audit` to check tag/TODO.md consistency.* -->
