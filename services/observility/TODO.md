# Observability Service — TODO

Implemented against `README.md`'s spec (2026-08-06). Full stack
(OTel Collector, Prometheus, Loki, Tempo, Grafana, Alertmanager, plus
cAdvisor and Promtail — both needed to actually deliver README's own
"Metrics"/"Logs" contract, see "Deviations from README's file tree"
below) brought up and smoke-tested end to end: all 8 containers reached
`healthy`/running, Prometheus loaded all 4 rule files (17 alert rules +
2 recording rules), Grafana auto-provisioned all 3 datasources and all
4 dashboards. Torn back down after — nothing is left running.

## Closed since initial implementation (2026-08-06)

- **`services/forecast-api` now exports `GET /metrics`.** Added
  `prometheus-client` dependency, `app/core/metrics.py`
  (`ecolens_forecast_predictions_total{region,cache}`,
  `ecolens_forecast_prediction_latency_seconds{region}` — server-side,
  deliberately named/labeled differently from data-pipeline's own
  caller-side `ecolens_forecast_requests_total`/`ecolens_forecast_latency_seconds`
  so the two don't collide under two scrape jobs), a `GET /metrics`
  route (`app/api/v1/health/routes.py`, no `/v1` prefix — matches the
  other 3 services' convention), and instrumented `GET /v1/forecast`
  itself (`app/api/v1/forecast/routes.py`). `prometheus/rules/forecast.yml`
  and `platform.yml` no longer special-case this job as permanently
  down; `PlatformServiceUnavailable` now covers it like every other
  job. Verified: forecast-api's full test suite (119 tests) + new
  `test_metrics_returns_prometheus_text` pass; `ruff check` clean.
- **`ecolens_ingest_runs_total{source,outcome}` is now actually
  incremented** — turned out to be a deeper gap than "ingestion is
  missing what data-pipeline has": the counter was defined in
  `data-pipeline`'s `core/metrics.py` and unit-tested in isolation, but
  **never incremented by either service's real ingestion code path**
  (`app/service/pipeline/tasks/_common.py` in both `data-pipeline` and
  `ingestion` — confirmed by grepping production code, not just tests).
  `ecolens:ingest_success_rate_24h` (this stack's own recording rule,
  and the prior simpler stack's `infra/prometheus/recording_rules.yml`
  before it) has therefore never had real data behind it in either
  service, in production, ever. Fixed in both: `services/ingestion/app/core/metrics.py`
  now defines the counter (it didn't before), and both services'
  `_common.py` increment it with `outcome="success"` (both the
  zero-rows no-op path and the normal staged path) or `outcome="failure"`
  (the except branch) alongside the existing `ingest_rows_total`/
  `ingest_failures_total` increments already there. Verified: both
  services' full test suites pass (ingestion: 354 passed/5 skipped;
  data-pipeline: 731 passed/5 skipped, 1 pre-existing unrelated failure
  — see below) plus new targeted tests in each `test_common.py`/
  `test_metrics.py` asserting the counter actually increments; `ruff
  check` clean on both.
  - **Pre-existing, unrelated failure found while verifying**:
    `services/data-pipeline/tests/test_landing.py::test_load_to_postgres_distinguishes_none_from_empty_string`
    fails on this Windows dev machine — it asserts a hardcoded `\n`-only
    CSV payload, but the code under test actually emits `\r\n` line
    endings here. Not touched by (or related to) this change; flagged
    for whoever owns `app/service/landing.py`/its test, not fixed as
    part of this pass.
- **`service`/`version` identity closed via a `build_info` metric —
  the "recommended next step" from this file's own prior note.** Added
  `ecolens_build_info{service,version}` (standard Prometheus "info
  metric" pattern, always `1`, labels carry the data) to all 4 business
  services' `core/metrics.py`, sourced from each service's own
  `app.__version__` at import time — not a hardcoded label in
  `prometheus.yml`'s scrape config, which would silently drift the
  moment a service ships a new version without someone remembering to
  update this stack too. Deliberately **not** a `relabel_configs`
  addition copying `job` into a `service` label: for these 4 scrape
  jobs, `job_name` already equals the service name 1:1
  (`job="data-pipeline"` etc.) — a relabel would be pure duplication,
  zero new information, whereas `build_info` also carries `version`
  (which `job` never could) and is sourced from the running app itself,
  the more authoritative origin. `environment=` intentionally still
  lives only on Prometheus's own `external_labels` (see below) — a
  compiled service binary has no business knowing its own deployment
  environment at the metrics layer when Prometheus already stamps it
  externally for every series regardless of source. Verified: all 4
  services' relevant test suites pass (data-pipeline 6/6 metrics tests,
  ingestion 7/7, warehouse 5/5 health-route tests, forecast-api
  120/120 full suite) with a new test per service asserting the exact
  label values; `ruff check` clean on all 4. **Still open**: the
  logging side of this same contract (`service`/`environment`/`version`
  bound to every structlog JSON line) — that needs a
  `structlog.configure()` static-context change in each of the 4
  services' own `core/logging.py`, a larger, more invasive change
  across 4 codebases than this metrics-side fix was; not done this
  pass.
- **Scrape targets are now cross-machine-configurable (2026-08-07)** —
  part of a repo-wide "make sure every service can independently
  deploy on a separate machine" pass. `prometheus/prometheus.yml` was
  hardcoded to Docker Compose service names (`data-pipeline:8001` etc),
  which only resolve on this stack's own `ecolens_default` network —
  fine for "everything on one host," not for a service that's actually
  moved elsewhere. Renamed to `prometheus.yml.template` and
  parametrized the 4 business-service targets
  (`DATA_PIPELINE_TARGET`/`INGESTION_TARGET`/`WAREHOUSE_TARGET`/
  `FORECAST_API_TARGET`, defaults in `.env.example` matching the exact
  values this file hardcoded before), rendered via a new
  `prometheus-config` init container (`envsubst`, same pattern
  `alertmanager-config` already established — Prometheus has no native
  `${VAR}` expansion either). One real snag while wiring this up:
  mounting the rendered-config volume onto `/etc/prometheus` wholesale
  made it read-only and broke the separate `rules/` bind mount nested
  inside it ("read-only file system" on container create) — fixed by
  mounting the config to its own dedicated `/etc/prometheus-config`
  directory instead (`--config.file=/etc/prometheus-config/prometheus.yml`),
  leaving `/etc/prometheus` itself unmounted so `rules/` nests inside
  it normally, same structural pattern `alertmanager` already uses
  (mount a directory, point the command flag at the file inside it —
  not mount a volume directly onto a file path). Verified: full
  `docker compose up -d` smoke test — all containers healthy, rendered
  config confirmed correct via `/api/v1/status/config`, targets and all
  5 rule groups loaded via `/api/v1/targets`/`/api/v1/rules`, a
  hand-substituted override with a real IP and a real hostname both
  rendered correctly. Torn down cleanly after. `docs/runbooks/
  independent-service-deployment.md` (repo root) documents the full
  cross-machine picture, including the (larger) fix this made necessary
  in `services/ingestion`/`services/data-pipeline`/`services/waerehouse`
  — see that doc.

## Known gaps (real, not yet closeable from inside this repo)

These aren't bugs in this stack — they're gaps in the *business
services* it monitors. Each is called out with a comment at its exact
usage site (`prometheus/rules/*.yml`, `grafana/dashboards/*.json`,
`prometheus/prometheus.yml`) so it isn't mistaken for silently-missing
config.

- **No service instruments generic HTTP-layer metrics**
  (`http_requests_total`, `http_request_duration_seconds`,
  `http_errors_total` — README's own example names). All four services
  only export domain-specific `ecolens_*` counters; none has
  `prometheus-fastapi-instrumentator` or equivalent wired in. README's
  "High HTTP error rate" / "High request latency" platform alerts are
  left as commented-out placeholders in `prometheus/rules/platform.yml`
  rather than silently dropped, so the gap isn't lost.
- **No OpenTelemetry SDK instrumentation exists in any of the four
  services** (confirmed: no `opentelemetry-*` application dependency in
  any `pyproject.toml`, only `mlflow`'s own transitive ones in
  forecast-api, unrelated to this). The OTel Collector and Tempo are
  both configured and ready (`otel/otel-collector-config.yml`) — point a
  service's OTLP exporter at `otel-collector:4317` (grpc) or `:4318`
  (http) once instrumentation lands. Until then Tempo/the Grafana trace
  view will simply have nothing in it — expected, not broken.
- **No RabbitMQ queue-depth metric exists anywhere** — carried forward
  from the prior, simpler stack's own note
  (`infra/prometheus/recording_rules.yml`'s original comment): there's
  no alert here for "warehouse-sync consumer is backlogged/down"
  because nothing exports open `status='staged'` run counts or queue
  depth as a metric. Would need a gauge added to
  `services/data-pipeline`/`services/waerehouse` first.
- **`service`/`version` on metrics is closed (see "Closed" section
  above); `environment`/`version` on structured logs is not.** No
  service's structlog config (`app/core/logging.py` in each of the
  four) binds `service`/`environment`/`version` as a static context
  field yet — a log line shipped via Promtail today carries no more
  than Docker's own container/service labels (added by Promtail's
  `docker_sd_configs` relabeling, `promtail/promtail-config.yml`), not
  an application-level `environment=`/`version=` field inside the JSON
  itself. Needs a small `structlog.configure()` static-context addition
  in each of the 4 services' `core/logging.py` — a real, symmetric,
  4-file change, just not done this pass (scoped out in favor of the
  metrics-side `build_info` fix above, which closed the higher-value
  half of this gap first).

## Deviations from README's documented "Repository Structure"

README's file tree (lines 178-214) doesn't list a Promtail config or a
cAdvisor entry. Both were added because the tree as written is
incomplete against README's own prose elsewhere in the same document:

- **`promtail/promtail-config.yml`** — README's own "Structured Logs"
  section says logs get collected by "Fluent Bit, Vector, or an
  equivalent agent," but the file tree only lists `loki/loki-config.yml`.
  Loki alone doesn't scrape/collect anything — it's a push target.
  Promtail (Grafana's own Loki-native shipper, consistent with the rest
  of this being an all-Grafana-Labs stack) fills that role, reading
  container JSON logs straight off the Docker socket — no code change
  or sidecar needed in any business service.
- **cAdvisor** (`docker-compose.yml`'s `cadvisor` service, no dedicated
  config file needed) — README's "Recommended Alert Examples" > Platform
  lists "High CPU / memory usage," but none of the four business
  services export process-level resource metrics themselves (confirmed
  by reading each `app/core/metrics.py`). cAdvisor is the standard,
  zero-service-code-change way to get container-level CPU/memory into
  Prometheus.

## Host port offsets vs. the root stack

`../../docker-compose.yml` already runs its own, simpler
prometheus/alertmanager/grafana/loki quartet
(`../../infra/{prometheus,alertmanager,grafana}/`) on 9090/9093/3001/3100
— the same default ports this stack's images normally claim. Rather than
silently deleting a working, currently-documented part of the root dev
stack (`../../README.md` lines 191, 423, 439, 745, 804 all reference it;
`make up`/`make down`/`make logs` depend on it), this stack's host ports
are offset instead, so both CAN run side by side without a collision:

| Component    | This stack (host) | Root stack (host) |
|---|---|---|
| Prometheus   | 9091               | 9090               |
| Alertmanager | 9094               | 9093               |
| Grafana      | 3002               | 3001               |
| Loki         | 3101               | 3100               |
| Tempo        | 3200               | — (doesn't exist)  |
| OTel Collector | 4317/4318/8888/13133 | — (doesn't exist) |
| cAdvisor     | 8085               | — (doesn't exist)  |

**Recommendation, not yet done**: this stack is a strict superset of the
root's inline one (same metrics, same alert rule content ported forward
— see `prometheus/rules/*.yml`'s own comments citing what was carried
over — plus logs/traces/dashboards/richer alerting the old one never
had). Once this stack is confirmed working in real day-to-day use, the
`prometheus`/`alertmanager-config`/`alertmanager`/`grafana`/`loki`
service blocks in `../../docker-compose.yml`, their `promdata`/`grafana`/
`alertmanagerconfig`/`alertmanagerdata` volumes, and `../../infra/{prometheus,alertmanager,grafana}/`
should be retired, and `../../README.md`'s references to them (lines
191, 423, 439, 745, 804) updated to point here instead. Not done as part
of this change — out of scope for implementing this service's own
README, and removing a working, documented part of someone else's dev
workflow deserves its own deliberate pass, not a side effect.

## Alertmanager receiver

`alertmanager/alertmanager.yml.template` uses a generic
`webhook_configs` receiver (`ALERTMANAGER_WEBHOOK_URL`, matching
README's own "Running this stack in production" section) rather than a
Slack-specific `slack_configs` block like the prior stack's template
did (`ALERTMANAGER_WEBHOOK_URL` vs. that one's `SLACK_WEBHOOK_URL`) —
deliberate, since README doesn't commit to Slack specifically anywhere.
Point the webhook at a relay into Slack/PagerDuty/whatever, or swap the
receiver block for `slack_configs`/`pagerduty_configs` directly if this
team wants native integration with one of those instead of a generic
webhook hop.

## Verification performed

- `docker compose config -q` — valid, and confirmed it refuses to start
  without `GRAFANA_ADMIN_PASSWORD`/`ALERTMANAGER_WEBHOOK_URL` set (via
  `${VAR:?...}` / a guard in `alertmanager-config`'s entrypoint).
- `promtool check config prometheus.yml` and
  `promtool check rules rules/*.yml` — both pass; 17 alert rules + 2
  recording rules across 4 files, all valid PromQL.
- Full `docker compose up -d` smoke test (temporary `ecolens_default`
  network, since the business services weren't running): all 8
  containers reached `healthy` (or running, for the two with no
  container-level healthcheck — `promtail`, `otel-collector`, matching
  README's own note about `otel-collector` having no shell to run one).
  Confirmed via API: Prometheus loaded all 4 rule groups; Grafana
  auto-provisioned all 3 datasources (Prometheus/Loki/Tempo) and all 4
  dashboards. Business-service scrape targets correctly showed `down`
  with a DNS-resolution error (expected — those services weren't
  running in this test). Torn down completely afterward
  (`docker compose down -v` + network removal) — nothing left running.
