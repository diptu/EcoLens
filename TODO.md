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
