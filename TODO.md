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
Looks like a finished product (32 pages, polished UI, "Lighthouse 100/100" in its own README) but has **no working backend integration at all** — this is the biggest gap in the whole project relative to how complete it appears.
- [ ] [ECO-130] **Wire real API integration.** Zero `fetch`/`axios`/`NEXT_PUBLIC_*` usage anywhere in `src/` — every page reads from a hardcoded 707-line mock object (`src/lib/data.ts`), not forecast-api/warehouse-api.
- [ ] [ECO-131] **Implement authentication.** The `(auth)/login` page (and presumably signup/reset) is a plain `<form>` with no `onSubmit`/handler/state — submitting it does nothing.
- [ ] [ECO-132] **Add a real data-fetching/state layer.** No React Query, SWR, Redux, or Zustand installed at all. (Note: root TODO previously said "migrate legacy state management to React Query" — there is no legacy state library to migrate *from*; this is a from-scratch addition, not a migration.)
- [ ] [ECO-133] **Add dashboard to CI.** Neither `main.yml` nor `ingest.yml` reference `services/dashboard` — no lint/test/build job exists for it.

---

## 🔧 Cross-Service / Infrastructure
- [ ] [ECO-141] **Fix `.github/workflows/ingest.yml`'s cron/comment mismatch.** Comment says "every 15 minutes"; the actual cron expression is `*/30 * * * *` (every 30 minutes).

---

<!-- *Legend: [ECO-XXX] refers to GitHub Issue ID. Run `make list-todos` to print all tagged TODOs across every service, `make audit` to check tag/TODO.md consistency.* -->
