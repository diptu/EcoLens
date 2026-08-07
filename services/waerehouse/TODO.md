# Warehouse Micro-Service — V2 Plan

V1 (see `README.md`) shipped all 5 phases live-verified: DuckDB→`raw.*` sync,
retention/pruning/cold-storage, dbt transforms into `raw_marts.*`, pipeline
API, CI. This is the next slice, scoped strictly to `services/waerehouse` —
byte-sized (each item is a few hours, independently shippable, independently
testable). Grounded against the actual current code, not the aspirational
overview doc alone.

## Phase 1: Fix mart history loss (correctness bug, do first) — DONE (2026-08-06)

`dbt_project.yml` materialized every mart `table` (full `CREATE TABLE AS
SELECT` rebuild each `dbt run`), sourced from `raw.*` via the staging views.
`app/retention/pruning.py` deletes anything older than `Settings.
retention_days` (60d) from `raw.*`. Put those two together: the **next**
`dbt run` after a prune rebuilt every mart from whatever's left in `raw.*`
— i.e. **silently dropped all mart history older than 60 days**, every
time. This directly contradicted `overview.md`'s Storage Policy ("curated
analytical tables... retain the complete historical dataset required for
forecasting, long-term trend analysis") and is why `forecast-api`/
`data-pipeline` reading `raw_marts.fct_energy_demand` could have lost
training history without anyone touching that code.

- [x] Confirmed the bug's mechanism by reproducing it end-to-end against a
      real Postgres 16 container (not assumed): seeded 10 days of synthetic
      `raw.*` rows, ran `dbt run` (2869 rows landed in `fct_energy_demand`,
      `min(ts)` = day 1), then pruned `raw.*` down to the last 3 days (the
      retention job's actual behavior) and confirmed a `table`-materialized
      rebuild would have brought `fct_energy_demand`'s floor forward to day
      8 — the exact loss `overview.md`'s Storage Policy promises can't
      happen.
- [x] Converted the 4 time-series marts (`fct_energy_demand`,
      `fct_emissions_5min`, `fct_carbon_intensity`, `fct_generation_mix`) to
      `+materialized: incremental`, `incremental_strategy: delete+insert`
      (dbt-postgres doesn't support `merge` — `delete+insert` is the
      correct, long-supported strategy for this adapter), each with its own
      `unique_key` matching its natural grain. Left `dim_energy_mix`/
      `dim_facility` on `table` — small reference/dimension sets, not time
      series, nothing to lose.
- [x] Added `{% if is_incremental() %}` filters: row-grain marts filter on
      `ts > max(ts) - 2 days`; hour-grain marts (`fct_carbon_intensity`,
      `fct_generation_mix`) filter the pre-aggregation `ts` against
      `max(hour) - 2 days` so a partially-populated hour gets its aggregate
      fully recomputed, not merged piecemeal. 2-day overlap absorbs
      late-arriving/corrected rows near the previous run's high-water mark.
- [x] Live-verified end to end (real Postgres 16, not mocked): after the
      simulated prune + a batch of new rows (the next ingestion cycle), a
      second `dbt run` kept the mart's full original history (`min(ts)`
      unchanged), picked up the new rows (`max(ts)` advanced, row counts
      grew by exactly the new rows), and introduced **zero duplicate keys**
      across all 4 marts (`count(*) - count(distinct <unique_key>) = 0`).
      `dbt test` still passes (51/51, minus one pre-existing placeholder
      test unrelated to this change — see README Phase 4's note).
- [x] Added a second `dbt run` step to `.github/workflows/ci.yml`'s
      `warehouse-dbt` job — the first run never exercises `is_incremental()`
      (relation doesn't exist yet), so without a second pass a broken
      incremental branch would pass CI silently.
- [x] Updated `README.md`'s Phase 4 note — it previously claimed incremental
      materialization was "already the shape," which was wrong (`table` ≠
      `incremental`); corrected in place with what actually shipped.

**Not done as part of this pass** (deliberately deferred, small enough to
pick up separately):
- A dbt/CLI check that asserts mart `min(ts)` never moves forward between
  scheduled runs in *production* — the live-verification above proved the
  mechanism works, but there's no automated guard watching the real NeonDB
  over time yet. Would need somewhere to persist the previous run's
  `min(ts)` to compare against (a small `meta.*` table, or a Prometheus
  gauge + alert rule) — genuinely a separate, small follow-up, not folded
  in here to keep this phase's diff reviewable.
- Running `dbt run --full-refresh` once against the **real** NeonDB the
  first time this deploys, so the existing `table`-built marts get a clean
  incremental baseline rather than dbt inferring incremental behavior on
  top of a relation it didn't build incrementally. Recommended before
  cutover, not done here (no live NeonDB access from this pass — everything
  above was verified against a disposable local Postgres 16 container).

## Phase 2: Carbon-insight completeness (per overview.md's explicit ask) — DONE (2026-08-06)

overview.md: *"Where renewable energy metrics are unavailable, the platform
derives the renewable proportion from the observed electricity generation
mix, ensuring carbon insights remain available even when external data is
incomplete."* `stg_openelectricity_mix.sql` previously passed
`total_renewable_mw` straight through from the raw provider column — no
fallback existed anywhere in the DAG.

- [x] `stg_openelectricity_mix.sql` now does
      `coalesce(provider_renewable_mw, <derived sum>) as total_renewable_mw`
      plus a sibling `renewable_mw_source` column (`'provider'` / `'derived'`
      / `null` when neither the provider figure nor any generation data was
      available for that row). The derived sum reuses exactly the fuel
      types `dim_energy_mix.sql` already classifies `is_renewable = true`
      (hydro, wind, solar_utility, solar_rooftop, biomass) — deliberately
      *not* pumped_hydro/battery_discharge (that model's own `storage`
      category) — so "what counts as renewable" stays defined in one
      place instead of picking a second, possibly-conflicting list here.
      Individual missing fuel readings are treated as 0 in the sum (not
      null-poisoning the whole total), but the derivation itself only
      fires when `total_generation_mw` is present — a row with no mix
      data at all still gets a genuine `null`, not a fabricated 0.
- [x] Added `assert_renewable_mw_within_total.sql` (singular test,
      `tests/`): fails if `total_renewable_mw > total_generation_mw` for
      any row, whether the figure was provider-reported or derived.
- [x] Added a `not_null` test on `total_renewable_mw` scoped with
      `config: where: "total_generation_mw is not null"`, plus an
      `accepted_values` test on `renewable_mw_source` (`['provider',
      'derived']`) — both in `models/staging/_staging__models.yml`.
- [x] Live-verified against a real Postgres 16 container (not just
      parsed): seeded 4 synthetic rows covering all 3 branches —
      provider-reported (used as-is), provider-null-but-mix-present
      (derived: `300+400+200+150+30 = 1080` MW, matched exactly),
      provider-null-with-one-fuel-column-also-null (derived treating the
      missing column as 0: `880` MW, matched exactly), and no-mix-data-at-
      all (both `total_renewable_mw` and `renewable_mw_source` correctly
      stayed `null`). `dbt test`: 53/54 pass (the 1 failure is the same
      pre-existing placeholder-value test noted in Phase 1, unrelated to
      this change). Full `pytest` suite: 55/55 still pass (no Python
      touched this phase).

**Not done as part of this pass**: propagating `renewable_mw_source` out
to `fct_energy_demand`/the dashboard for end-user visibility into which
rows used the fallback — `int_demand_with_weather.sql` currently only
selects `total_renewable_mw` from the staging model, not the new source
flag. Small, additive follow-up if the dashboard wants to surface it;
not required for the carbon-insight numbers themselves to be correct.

## Phase 3: Anomaly-awareness in the curated layer (per overview.md's ask) — DONE (2026-08-06)

overview.md: *"every ingested record is analysed... flagged with an anomaly
score and explanation, enabling downstream systems and users to
differentiate between data quality issues and real-world grid events."*
Previously that flag died at ingestion — `meta.anomalies` lives in the same
NeonDB `raw.*`/`raw_marts.*` already connects to, but no dbt source/model
read it, so nothing downstream of the warehouse (dashboard, forecast-api)
could see it.

- [x] Added `meta` as a second source schema (`models/staging/_sources.yml`,
      `source('meta', 'anomalies')`) — same `DATABASE_URL`, no new
      connection. **Real finding while building this**: `meta.anomalies`
      has no first-class `ts`/`region` columns at all — `services/
      ingestion`'s `record_anomalies` (`anomaly.py`) writes the flagged
      record's *entire original row* as a `row_snapshot` jsonb blob
      instead (shape varies per source table), keyed only by `source`/
      `table_name`/`detected_at`. The Phase 1 plan's "`(ts, source,
      metric)`" passthrough assumption was wrong — confirmed by reading
      `services/data-pipeline/migrations/0015_anomalies.sql` (the real
      table DDL) before writing any model, not assumed.
- [x] New `stg_anomalies.sql` (view) — extracts `ts`/`region`/
      `network_code` out of `row_snapshot` (`->> 'ts'`, cast to
      `timestamptz`, etc.), scoped to the 3 sources that actually have a
      usable `(ts, region)` shape: `aemo_nem_dispatch`/`aemo_wem_dispatch`
      (demand) and `openelectricity_mix` (mix). `bom_observations` (keys
      on `station_id`, not `region`, directly) and `aemo_holidays` (no
      `ts`, annual snapshot) are deliberately out of scope for *this* join
      — their anomalies still exist in `meta.anomalies`, just aren't
      surfaced through this particular join.
- [x] New `int_anomaly_by_demand.sql` / `int_anomaly_by_mix.sql`
      (ephemeral) — worst anomaly (`anomaly_score` desc, `detected_at`
      desc tiebreak) per `(ts, region)` / per `(hour, network_code,
      region)` respectively, since `fct_generation_mix` is hourly-
      aggregated and a row-level mix anomaly needs rolling up first.
- [x] Left-joined onto `fct_energy_demand` (`is_anomalous` / `anomaly_score`
      / `anomaly_reason`) and `fct_generation_mix` (same 3 columns, shared
      across every `fuel_type` row for that hour — the flag is on the mix
      reading, not one fuel in isolation). Left join, nothing filtered —
      same "preserve the record, just flag it" contract `ingestion/app/
      service/pipeline/anomaly.py` already established.
- [x] Added a conditional `not_null` test (`config: where: "is_anomalous"`)
      on `anomaly_reason` for both marts, plus `not_null`/`unique`/
      `accepted_values` tests on the new `stg_anomalies` columns.
- [x] Live-verified against a real Postgres 16 container (schema mirroring
      the real `meta._ingest_log`/`meta.anomalies` migrations, not a
      simplified stand-in): seeded 4 demand rows + 2 mix rows with one
      genuine demand spike and one matching mix anomaly, plus an
      out-of-scope `bom_observations` anomaly. Result matched exactly —
      only the spike row came back `is_anomalous = true` with the correct
      `anomaly_score`/`anomaly_reason`, every clean row stayed `false` with
      null score/reason, the `bom_observations` anomaly correctly never
      appeared in `stg_anomalies`, and a second `dbt run` (incremental
      path) reproduced the same result with zero duplicate rows. `dbt
      test`: 66/67 pass (same pre-existing placeholder-value test from
      Phase 1/2, unrelated). `pytest`: 55/55.

**Not done as part of this pass**: joining anomaly awareness into
`fct_carbon_intensity`/`fct_emissions_5min` too (only `fct_energy_demand`/
`fct_generation_mix` were in the original Phase 3 scope) — `int_anomaly_
by_mix` already computes the hourly mix-anomaly rollup those 2 marts would
need, so extending this is a small, additive follow-up, not a redesign.

## Phase 4: Production cutover & deploy hardening — DONE (2026-08-06)

Carried over from README's own "Explicitly not done" list.

- [x] **Cutover switch, not a cutover** — the actual cutover (stopping
      `data-pipeline`'s consumer) is still an operational decision for
      whoever owns that service's deploy, not made here. What shipped:
      `Settings.warehouse_sync_consumer_enabled: bool = True`
      (`services/data-pipeline/app/core/config.py`) — `app/service/
      worker.py`'s `run()` now checks it first and returns immediately
      (no RabbitMQ connection opened at all) when `False`. Default `True`
      preserves today's behavior exactly; an operator flips
      `WAREHOUSE_SYNC_CONSUMER_ENABLED=false` once this service is
      trusted, instead of deleting `app.service.worker`/the
      `warehouse-sync` compose service outright — reversible right up
      until that flag (and the dead code behind it) is actually removed
      later. New test: `services/data-pipeline/tests/test_worker.py::
      test_run_is_a_noop_when_warehouse_sync_consumer_disabled`. 3/3
      `test_worker.py` tests pass.
- [x] **`docker compose up warehouse` end-to-end, live-verified on the
      real compose network** — the previously-blocking port-5432
      conflict wasn't reproducible this pass (port was free), but the
      root cause is real and now fixed anyway: `docker-compose.yml`'s
      `postgres` service host port is now `${POSTGRES_HOST_PORT:-5432}`
      instead of a hardcoded `5432` — an operator whose machine already
      has a native Postgres bound to 5432 can override it via `.env`
      without touching the compose file, container-to-container traffic
      unaffected either way. **2 more real bugs found and fixed while
      actually getting this running**, neither hypothetical:
      1. A stale `ecolens_default` Docker network (mislabeled, left over
         from an unrelated prior run) blocked `docker compose up` outright
         (`network ecolens_default was found but has incorrect label`).
         Not this repo's bug and not touched (it turned out to be in
         active use by a separate, already-running `ecolens-observability`
         stack on the same machine) — verified instead under an isolated
         `-p` project name.
      2. **`infra/docker/warehouse.Dockerfile` never installed `wget`**,
         but `docker-compose.yml`'s own healthcheck for this service is
         `CMD wget -qO- http://localhost:8004/v1/healthz` — confirmed via
         `docker inspect`'s health log: `FailingStreak` climbing forever,
         `exec: "wget": executable file not found in $PATH`, even though
         `/v1/healthz`/`/v1/readyz` answered correctly the entire time
         over the published port. Fixed: `wget` added alongside the
         existing `git` install. **Same gap exists in every sibling
         service's Dockerfile** (`ingestion`/`forecast-api` install
         neither wget nor curl; `data-pipeline` installs curl, not wget,
         so its identical wget-based healthcheck is equally broken) —
         out of scope to fix here since only this service was asked for;
         flagging so it isn't lost.
      After both fixes: brought up `postgres`+`rabbitmq`+`minio`+
      `minio-setup`+`warehouse`+`warehouse-consumer` on the real compose
      network (isolated `-p ecolens-warehouse-verify` project name so
      the unrelated `ecolens_default` network/stack above was never
      touched), confirmed `GET /v1/readyz` over the published port
      returns `{"status":"ready","components":[{"name":"postgres",
      "healthy":true},{"name":"rabbitmq","healthy":true}]}`, and the
      container's own Docker healthcheck reports `healthy` (not just
      "starting" forever). Torn down cleanly afterward (`down -v`) —
      nothing left running.
- [x] **`dbt source freshness` — real bug found and fixed, then run
      live to success.** The CLI's own documented example
      (`ecolens-warehouse dbt source freshness`) never actually worked:
      `run_dbt` built `["dbt", subcommand, "--project-dir", ...]`, which
      is correct for a single-word subcommand but wrong for a multi-word
      dbt command path — confirmed directly against the real `dbt` CLI
      that `--project-dir`/`--profiles-dir`/`--target` must come *after
      every word* of the path (`dbt source freshness --project-dir X`
      works; `dbt source --project-dir X freshness` doesn't —
      `Error: No such option '--project-dir'`). Worse: click's own
      argument parsing splits `ecolens-warehouse dbt source freshness`
      into `subcommand="source"`, `extra_args=("freshness",)` before
      `run_dbt` ever sees it, so even a naive "put flags after every word
      of `subcommand`" fix wouldn't have been enough on its own. Fixed in
      `app/dbt/runner.py`: `subcommand.split()` seeds the path, then
      leading non-flag (`-`-prefixed) tokens are popped off `extra_args`
      and appended to it too — handles both a pre-joined string
      (`run_dbt("source freshness")`) and the click-split call shape
      the CLI actually produces. Metric/log labels now use the full
      resolved path (`"source freshness"`, not just `"source"`) so
      Prometheus can tell the two apart. New tests:
      `tests/test_dbt_runner.py` (6 tests — single-word unchanged,
      both multi-word call shapes, real flags not swallowed as path
      segments, multi-word-plus-trailing-flags, metric/log label
      correctness). **Live-verified end to end** via the actual
      `ecolens-warehouse` CLI against a real Postgres 16 container:
      seeded one fresh row per source, ran `ecolens-warehouse dbt source
      freshness` — **4/4 sources PASS**. Also confirmed the failure mode
      directly (before seeding fresh data, and separately against this
      machine's own native Postgres with different credentials) to make
      sure the fix reaches real dbt argument parsing and a real DB
      connection attempt, not a mocked shortcut. Not yet wired into a
      cron/CI surface alongside `prune`/`vacuum`/`check-size` — small,
      additive follow-up once an operator decides the right cadence.
- [x] Fixed the stale doc comment in `models/staging/_sources.yml` — no
      longer credits `pipeline.warehouse_sync` alone; now describes the
      real current state (either of 2 consumers can land a given row,
      both write the identical shape) and points at the cutover switch
      above for how that resolves to one.

## Phase 5: Retention-policy documentation — DONE (2026-08-06)

- [x] Added an explicit **Storage Policy** section to `README.md`
      (previously this fact only lived inside Phase 1's changelog entry,
      easy to miss): `raw.*`'s 60-day retention applies *only* to
      `raw.*`, never to `raw_marts.*` — stated plainly so a future
      "let's simplify the marts back to `table`" change doesn't
      unknowingly reintroduce the Phase 1 bug.
- [x] Confirmed `data-pipeline`'s training query doesn't assume a fixed
      history depth: `app/service/ml/data.py`'s `load_training_data`
      queries `raw_marts.fct_energy_demand` with no `LIMIT` and only an
      optional caller-supplied `since` filter — it naturally scales to
      whatever history the mart actually holds, no hardcoded day-count
      to go stale. Stronger finding along the way: a comment on that same
      file (line ~351) records `fct_energy_demand` holding "~55K rows,
      ~4 months of history" at the time it was written — well past the
      60-day floor Phase 1's bug would have silently reset it to on the
      next `dbt run`, concrete confirmation the bug was live-impactful,
      not just theoretically possible.

## Prod-Grade Hardening Pass — DONE (2026-08-06)

User-requested scope: close out the gaps this file had already logged as
"not done" across Phases 1–4, plus deploy readiness. (Security/auth
hardening and actually flipping the legacy-consumer cutover were offered
as options and explicitly *not* selected — still open, not touched here.)

### Closed gaps

- [x] **Phase 1's mart-history regression monitor.** Original plan was a
      Prometheus gauge + `delta()` alert rule — caught a real design flaw
      before shipping it: `check-mart-history` is meant to run from
      `.github/workflows/warehouse-monitor.yml`'s scheduled job, a fresh
      GitHub Actions runner every time, never the actual deployed (and
      Prometheus-scraped) `warehouse` service — a gauge set there dies
      with the process and never reaches Prometheus at all. Redesigned:
      new migration `0003_mart_floor_checks.sql` (`meta.mart_floor_checks`
      — one row per mart, the last-observed floor), `app/retention/
      mart_floor_monitor.py`'s `check_mart_floors()` compares the current
      `min(ts)`/`min(hour)` against that persisted value (the one thing a
      CI job and the real deployed service always share: the same
      production database) and flags `regressed=True` if it moved
      forward. New `check-mart-history` CLI command exits nonzero on any
      regression (same shape `check-size` already uses) — the GitHub
      Actions job going red *is* the alert, same pattern `ingest-*.yml`
      already established, no Prometheus alert rule needed. `mart_min_ts_
      seconds` gauge still added for `/metrics` visibility, explicitly
      documented as visibility-only, not the alerting mechanism. 7 new
      unit tests (`tests/test_mart_floor_monitor.py`) + 2 CLI tests.
      **Live-verified against a real Postgres 16 container**: seeded 5
      days of history, ran `check-mart-history` (baseline, exit 0), then
      deleted the oldest 2 days directly from the mart (simulating
      exactly what a reverted-to-`table` materialization would do), ran
      it again — correctly flagged `fct_energy_demand -- REGRESSED (lost
      history)`, exit 1. Ran a third time — new floor stable, exit 0
      again (doesn't keep re-flagging an unchanged value).
- [x] **Phase 2's `renewable_mw_source` propagation.** Added to
      `int_demand_with_weather.sql`'s generation lateral join and its
      final select — flows through to `fct_energy_demand` automatically
      (that mart is a bare `select *` over it). New schema test
      (`accepted_values` on `int_demand_with_weather`). **Live-verified**:
      a demand+mix row pair inserted with an exactly-matched timestamp
      (avoids a pre-existing, unrelated "as-of join" timing quirk explained
      below) showed `renewable_mw_source='derived'`,
      `total_renewable_mw=1165` — matched the hand-summed per-fuel total
      exactly.
- [x] **Phase 3's anomaly-awareness, extended to the other 2 marts**
      (`fct_carbon_intensity`, `fct_emissions_5min` — originally only
      `fct_energy_demand`/`fct_generation_mix` had it). `fct_carbon_
      intensity` is the same `(hour, network_code, region)` grain
      `int_anomaly_by_mix` already produces — reused directly, no new
      model needed. `fct_emissions_5min` is row-grain
      `(ts, network_code, region)` — new ephemeral `int_anomaly_by_mix_
      row.sql` (the row-level counterpart of `int_anomaly_by_mix`).
      **Live-verified**: seeded one flagged demand row + one flagged mix
      row at a shared hour, confirmed `is_anomalous`/`anomaly_score`/
      `anomaly_reason` landed correctly on exactly the right rows across
      all 4 marts (`fct_energy_demand`, `fct_generation_mix`,
      `fct_carbon_intensity`, `fct_emissions_5min`) — including that
      `fct_carbon_intensity`/`fct_emissions_5min` correctly picked up the
      *mix*-table anomaly, not the demand one. `dbt test`: 73/74 (same
      pre-existing placeholder-value test, unrelated). Second `dbt run`:
      zero duplicate keys across all 4 marts.
- [x] **Phase 4's `dbt source freshness`, wired into a scheduled
      surface.** New `.github/workflows/warehouse-monitor.yml` — hourly
      `schedule` + `workflow_dispatch`, same "GitHub Actions `schedule` as
      free interim cron" pattern `ingest-*.yml` already established
      (`docs/runbooks/github-actions-secrets.md`, extended with this
      workflow's own secrets section). Runs `dbt source freshness` +
      `check-size` + `check-mart-history` — deliberately **read-only**;
      `prune`/`export-and-prune` are genuinely destructive (delete `raw.*`
      rows) and were **not** put on a schedule here, matching this
      project's consistent stance that when-to-prune is an explicit
      operator decision, not something to quietly automate without being
      asked for that specifically.

### Deploy readiness

- [x] **Deploy-on-merge CI for the warehouse image.** `data-pipeline`/
      `forecast-api` already had this (`.github/workflows/docker.yml` —
      build+push to GHCR on `main`/tags, using the built-in
      `GITHUB_TOKEN`, no extra secrets); `warehouse` wasn't in the matrix.
      Added — same zero-extra-secrets pattern, no new infra invented.
- [x] **Prometheus wasn't scraping `warehouse` at all.** Found while
      building the mart-floor monitor above (checking whether a Prometheus-
      based design was even viable): `infra/prometheus/prometheus.yml` had
      scrape jobs for `data-pipeline`/`forecast-api` only. Every
      `ecolens_warehouse_*` metric (`/metrics`, Phase 5 of V1) has existed
      and been populated since V1 shipped but never actually reached
      Prometheus/Grafana/Alertmanager. Added the `warehouse:8004` scrape
      target.
- [x] **Resource limits on `warehouse`/`warehouse-consumer`**
      (`docker-compose.yml`) — `deploy.resources.limits` (1 CPU/1GB API,
      1 CPU/2GB consumer — higher memory ceiling than the API, DuckDB
      reads + pyarrow COPY loads are heavier per-message), same mechanism
      `train-worker` already established for plain `compose up` (not just
      swarm).
- [x] **Graceful SIGTERM shutdown for the consumer.** `cli.py`'s
      `consume` command only ever handled `KeyboardInterrupt` (SIGINT) —
      `docker stop`/an orchestrator sends SIGTERM, which Python doesn't
      turn into a catchable exception by default, so the process would
      just run until the container's stop grace period elapsed and
      SIGKILL ended it. New `app/db/rabbitmq.run_consumer_forever`
      registers a SIGTERM handler (`loop.add_signal_handler`, falls back
      to a no-op on Windows — every real deployment is Linux) that
      cancels the consume loop and closes the RabbitMQ connection
      cleanly. **Not a data-safety fix** — `consume_landed_events` only
      acks a message *after* its handler succeeds, so a message in flight
      when killed was always safely redelivered either way (SIGTERM or a
      bare SIGKILL); this is about exiting promptly with a clean log line
      instead of relying on SIGKILL as the only way this process ever
      stops. 2 new tests (`tests/test_rabbitmq.py`) — one exercises a
      real `os.kill(os.getpid(), signal.SIGTERM)` against a hanging fake
      queue (skipped on Windows, where `add_signal_handler` isn't
      implemented — runs for real on CI's `ubuntu-latest`).

**Not done as part of this pass** (explicitly out of scope per the
options offered): security/auth hardening on the currently-open REST
endpoints; actually flipping `WAREHOUSE_SYNC_CONSUMER_ENABLED=false` to
complete the legacy-consumer cutover (the config switch exists — Phase
4 above — flipping it is still an operator decision); applying migration
`0003_mart_floor_checks.sql` against the real NeonDB (needed before
`warehouse-monitor.yml`'s `check-mart-history` step will do anything but
fail on a missing table — a manual `scripts/apply-migrations.sh` run,
same as every other migration in this project).

All verification this pass used disposable local Postgres 16 containers
(no live NeonDB/GitHub Actions secrets access from this session) — `dbt
test`: 73/74 (1 pre-existing, unrelated placeholder). `pytest`: 71 passed,
1 skipped (the Windows-only SIGTERM test). `ruff check`/`mypy app`: clean.

### Re-verification (2026-08-06, later same day)

Re-ran the full suite after `app/core/metrics.py` picked up an unrelated
external edit (`build_info` gauge, part of a separate observability
initiative touching every service — not this pass's work, not reverted).
Confirmed the two changes coexist fine and nothing regressed:

- `services/waerehouse`: **72 passed, 1 skipped** (one more than before —
  the external `build_info` change added its own test), `ruff check`/
  `mypy app` clean, `dbt parse` clean.
- `services/ingestion`: 354 passed, 5 skipped.
- `services/forecast-api`: 120 passed.
- `services/data-pipeline`: 735 passed, 5 skipped, **1 failed** —
  `tests/test_landing.py::test_load_to_postgres_distinguishes_none_from_empty_string`.
  **Pre-existing, unrelated to this pass or to warehouse**: asserts a CSV
  byte-string equals `"1.0,x\n\\N,\n"`, but pandas' CSV writer defaults to
  `\r\n` line endings on Windows — the assertion hard-codes `\n` only.
  Would pass on CI's `ubuntu-latest` runner (pandas defaults to `\n`
  there); fails locally on this Windows dev machine regardless of
  anything in this session. Neither `landing.py` nor `test_landing.py`
  were touched by any work in this file — not fixed here, flagged instead
  since it's out of this service's scope and wasn't asked for.

No other regressions found. Everything this "prod grade" pass shipped is
still verified working.

## Cross-machine deployment — DONE (2026-08-07)

User request: make sure every service can independently deploy on a
separate machine. Audited this service's own real coupling points
against `services/ingestion`/`services/data-pipeline` and found one
genuine blocker: `app.db.duckdb_client.read_run` only ever read the
shared `duckdb_staging` Docker volume `services/ingestion` writes into
— correct on one host (today's `docker-compose.yml` default), silently
wrong on two. Worse than an error: a missing shared file made `read_run`
return an **empty DataFrame** (its own documented "already consumed,
not a bug" case for a redelivered message) — so a genuinely
different-host `services/ingestion` would have looked like it was
working (`meta._ingest_log` marked `"success"`) while actually
syncing **zero rows**, every time.

- [x] `app/db/object_storage.py` gained `download_bytes` — was
      upload-only before ("nothing in this service ever reads
      cold-storage exports back" was true of *cold-storage exports*
      specifically, not of this new concern: reading `services/
      ingestion`'s own staging snapshots back). New `tests/
      test_object_storage.py` (this service had no dedicated test file
      for this module before).
- [x] New `db.duckdb_client.read_run_with_fallback`: tries the shared
      local file first (same-host fast path, byte-for-byte the same as
      `read_run` always was), falls back to downloading+reading the
      run's object-storage snapshot only when the local file is
      genuinely absent (the unambiguous "different host" signal — a
      file that exists but doesn't have this particular run's rows
      still returns empty exactly as before, unchanged, since that's a
      real same-host case too: an already-consumed redelivery, safe to
      no-op given `loaders.postgres_loader.load_to_postgres`'s
      `ON CONFLICT DO NOTHING` natural-key dedup).
- [x] `consumers.landed_events.sync_landed_event` now reads
      `object_storage_key`/`_bucket` off the payload (`.get()`, not
      `[]` — absent is expected whenever this event didn't come from
      `services/ingestion`'s current producer) and threads them
      through.
- [x] Created `.env.example` for this service — **didn't exist before**,
      unlike every sibling service. A real gap for "can this service be
      independently deployed": there was nothing telling an operator
      what env vars to set.
- [x] `dbt/ecolens/profiles.yml`'s `prod` target no longer defaults
      `host` to the literal Docker Compose service name `postgres` —
      no default at all now, so a real deployment that forgets
      `POSTGRES_HOST` gets an immediate, clear dbt error instead of a
      silent attempt to resolve a hostname that only exists on one
      specific Docker network.
- [x] New `docs/runbooks/independent-service-deployment.md` (repo
      root) — consolidates this fix plus the matching one in
      `services/data-pipeline`, the competing-consumer flag
      (`WAREHOUSE_SYNC_CONSUMER_ENABLED`) operators need to know about
      when choosing which consumer is "the real one" in an independent
      deployment, and `services/observility`'s new cross-machine
      scrape-target env vars.

**Verified**: 14 new tests (`test_object_storage.py` +
`TestReadRunWithFallback` in `test_duckdb_client.py` + updated
`test_landed_events.py`), full suite **83 passed, 1 skipped** (up from
72), `ruff check`/`mypy` clean on every changed file. Sibling fix in
`services/data-pipeline` (`duckdb_staging.read_staged_with_fallback`,
same pattern) verified separately — see that service's own test run,
749 passed/5 skipped, same 1 pre-existing unrelated failure.
