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

### 🗄 Historical raw-data archive (DuckDB cold storage)
`warehouse/runner/archive.py`'s `ArchiveManager.archive()` (Stage 6 of the
7-stage `WarehouseRunner`) is named and documented as "move old raw data to
cold storage" but the implementation only ever calls Mongo's
`delete_many({"fetched_at": {"$lt": cutoff}})` — there is no cold-storage
write anywhere. With `archive_after_days` defaulting to 365, every AEMO
NEM/WEM, OpenElectricity, and BoM raw document older than a year is
permanently destroyed today, and nothing else in the stack retains history
that far back (dbt's incrementals only look back 5 days; the ML training-set
rebuild looks back 3 years but reads Postgres marts, not raw docs). DuckDB is
the right fit for the actual cold store: no server process, native
partitioned-Parquet writer, and it can query directly against the MinIO
bucket the repo already provisions (`s3_bucket_raw` in `config.py`) via its
`httpfs` extension — so ad-hoc historical queries (drift investigations,
"what did AEMO report before a settlement correction") never have to touch
live Mongo/Postgres.
- [✓] [ECO-158] **Historical-backfill DuckDB store landed (both the CLI
  script and the real `/ingestion/historical` API, all 5 sources).**
  `ingestion/storage/duckdb_store.py` — `write_historical()`/
  `read_historical()`, one table per source (named after
  `MongoSettings.collection_for_source`), upserted on
  `MongoSettings.unique_key_for_source` so re-running a backfill is
  idempotent. `HistoricalFetcher.write_duckdb()` (bom/historical.py) owns
  the call for `scripts/backfill_bom_historical.py`, mirroring the
  existing `write_cache()` method. Separately, `ingestion/api.py`'s real
  `POST /ingestion/historical` endpoint (landed on `dev` via "feat
  (ingestion): Ingestion v0.0.1", commit 8c994cd -- a whole 712-line
  router with job-id-based background processing that this branch had
  missed until it was merged in here) writes to a *separate*
  `MONGO_URI_HISTORICAL` cluster and, until this fix, never touched
  DuckDB at all -- confirmed live: a job triggered before this landed
  (`job_id=f257467d50184a60a824992e3db9a72e`) has no DuckDB rows. Added
  `_write_duckdb_best_effort()` in `ingestion/api.py`, called from all
  four `_ingest_*_historical` functions (bom, aemo_nem/wem,
  openelectricity, holidays) right after their `bulk_upsert`, using each
  function's actual Mongo collection key (holidays upserts under
  `"aemo_holidays"`, not `"holidays"` -- covered by a regression test).
  Runs regardless of the `historical` flag, so `/ingestion/retry-missing`
  (live-cluster repairs) also lands in DuckDB.
  `duckdb` added to `services/data-pipeline/pyproject.toml`; new
  `Settings.historical_duckdb_path` (default `data/historical/`, same
  local-disk convention as `bom_cache_dir`/`training_snapshot_dir`). Tests
  in `tests/test_ingestion_storage_duckdb.py`,
  `tests/test_bom_historical.py::TestWriteDuckdb`, and
  `tests/test_ingestion_api.py`'s `TestIngest*Historical` classes. This
  is a **single-file upsert store**, not the partitioned-Parquet cold
  store ECO-150 below describes, and it's not wired into
  `ArchiveManager`. ECO-150 should extend/reuse this module rather than
  starting a new one.
- [ ] [ECO-150] **Add a `DuckDBArchiveStore` writer for `ArchiveManager`.**
  Extend `ingestion/storage/duckdb_store.py` (see ECO-158 — reuse it,
  don't fork it) or add a sibling in `warehouse/runner/` that writes a
  batch of raw Mongo docs to partitioned Parquet
  (`collection=<name>/year=<yyyy>/month=<mm>/`), partitioned by each
  source's own event timestamp, not `fetched_at`. `duckdb` dependency is
  already added.
- [ ] [ECO-151] **Rewire `ArchiveManager.archive()` to back up before
  deleting.** `find()` the docs older than cutoff, write them via
  `DuckDBArchiveStore`, verify the write (row count matches), only then
  `delete_many` the same filter. Today `archive()` unconditionally returns
  `success=True` with no failure path at all — a failed write must return
  `success=False` and skip the delete for that collection, never
  delete-before-backup.
- [ ] [ECO-152] **Derive archived Parquet schema from the existing pandera
  validators**, not raw heterogeneous JSON. Each source already has a
  typed schema in `ingestion/validators/{aemo,bom,holidays,openelectricity}.py`
  — reuse it so the archive stays typed/queryable instead of hitting the
  "different shapes, different time zones, holidays aren't even a time
  series" problem `warehouse/werehouse.md` already calls out.
- [ ] [ECO-153] **De-dupe archived rows on each source's compound unique
  key** (`MongoSettings.unique_key_for_source()`), so re-running archive
  over an overlapping cutoff window (retry, clock skew) never writes the
  same row twice into the Parquet store.
- [ ] [ECO-154] **Wire the archive target through existing settings, not a
  new surface.** Add `archive_store_path` to `WarehouseRunnerSettings` for
  the local dev default; reuse `Settings.s3_endpoint_url`/`s3_access_key`/
  `s3_secret_key`/`s3_bucket_raw` (already in `config.py`) as the optional
  MinIO/S3 target via DuckDB's `httpfs`, per the "don't invent a second
  settings object" rule in CLAUDE.md.
- [ ] [ECO-155] **Add a read path.** The archive is write-only otherwise —
  extend `warehouse/runner/cli.py` with an `archive-query` subcommand
  (collection, region, date-range → matching rows) so archived history is
  actually retrievable, not just a backup nobody can query.
- [ ] [ECO-156] **Tests.** Extend `tests/test_warehouse_runner_archive.py`
  (currently only asserts `delete_many` counts via `FakeMongoCollection` —
  has no concept of a prior write step) and add
  `tests/test_warehouse_runner_duckdb_archive.py`: write/read round-trip
  against a `tmp_path` store, delete only fires after a successful write,
  and the regression case — write raises → Mongo `delete_many` must NOT be
  called.
- [ ] [ECO-157] **Fix the docs once it's real.** `archive.py`'s Stage 6
  docstring and `werehouse.md`'s "What's where" cheat sheet both currently
  describe cold storage that doesn't exist yet — update them to point at
  the DuckDB/Parquet location once ECO-150..156 land.

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
