# services/ingestion — Implementation TODO


**Ingestion Pipeline Mechanism** — Every 5 and 30 minutes, respective
scheduled cron triggers dispatch asynchronous background tasks managed
by Celery to ingest operational energy data from external REST APIs
across their distinct polling intervals. Incoming payloads are captured
and staged in a local DuckDB instance for normalization and
preparation. Once processed, Celery publishes completion events via
RabbitMQ to notify the downstream warehouse service, an event-driven,
decoupled foundation for warehousing, forecasting, and carbon
accounting.

**Anomaly Detection Layer** — every ingested record is analysed with a
hybrid approach combining rule-based checks with machine learning
models. Suspicious records are flagged with a score + explanation, not
removed, so downstream systems/users can tell data-quality issues apart
from real grid events.

**Storage** — DuckDB as lightweight local staging instead of writing
every record straight to the cloud warehouse; once staged, data is
published to the event-driven warehousing pipeline for validation/
transform/long-term storage in PostgreSQL. All artefacts (including
model weights) end up in Cloudflare R2.

## Ground truth — what's already real, right now

- **Celery now exists** (`app/celery_app.py`, `app/service/pipeline/
  tasks/celery_tasks.py`) — RabbitMQ-broker/Redis-backend, a single
  unified `beat_schedule` entry (`ingest-all-sources`, every 30 min,
  fans out to all 5 sources via `celery.group`), `ecolens-ingestion
  worker`/`beat` CLI commands, `docker-compose.yml` `ingestion-worker`/
  `ingestion-beat` services. Live-verified against real local RabbitMQ +
  Redis (see "Remaining Work" §1's own update notes for the full
  verification). One of *four* independent ways ingestion gets
  triggered, not a replacement for the others: direct async calls
  (`pipeline.tasks.registry.run_source`), the CLI's `ingest`/`backfill`
  commands, two HTTP surfaces (`POST /v1/ingest/{source}` — synchronous,
  registry-key; `POST /v1/data-sources/{id}/run` — `202`-backgrounded,
  catalog-id), and now Celery Beat. **2026-08-05 — the drafted
  `.github/workflows/ingest-*-ingestion-service.yml` cutover workflows
  have been removed** (they were untracked/never committed) — Celery
  Beat is the settled scheduler going forward, resolving §1's last open
  item. The *legacy* per-source `ingest-{source}.yml` workflows
  (`data-pipeline`'s own real, currently-live `schedule:`-triggered
  cron) are untouched by this — a separate decommission step (Phase 6,
  still not started) once this service's Celery-driven ingestion is the
  verified real replacement.
- **Real per-source cadences** (`app/models/datasources.py`'s
  `CATALOG`, already correct — not literally "5 and 30 minutes" for
  everything): `oe` every 5 min, `aemo-nem`/`aemo-wem` every 15 min,
  `bom` every 30 min, `holidays` once a year.
- **DuckDB staging**: real, and further along than "basic" — a single
  shared `landed.duckdb` file (not one-per-run), one real table per
  source, rows tagged `_ingest_run_id` so runs stay distinguishable
  within a shared table, forward-schema-drift-safe
  (`app/service/pipeline/duckdb_staging.py`).
- **RabbitMQ publish**: real (`app/db/rabbitmq.py`'s `publish_landed_
  event`, called from `pipeline.tasks._common.standard_run` after every
  successful stage). Publish-only — this service never consumes; a
  `triggered_by="shadow"` run publishes to a separate shadow queue so
  it never gets double-loaded downstream.
- **R2 object storage**: real (`app/service/object_storage.py`) — every
  run's staged rows are extracted into a small per-run snapshot and
  uploaded under `staging/{table}-{run_id}.duckdb`, idempotency-checked
  before upload; ML model artifacts under `models/anomaly/{source}.
  joblib` (same mechanism). Falls back to local MinIO when no real R2
  credentials are configured. **2026-08-05 — real R2 now genuinely
  configured and verified live** in this environment: `services/
  ingestion/.env` had R2 config under the *wrong* variable names
  (`ACCOUNT_ID`/`S3_API`/`BUCKET_NAME` instead of the `CLOUDFLARESTORAGE_
  *` names `app/core/config.py` actually reads) and no access/secret key
  at all, so `object_storage_configured` was silently `False` — fixed
  the names, real credentials added, confirmed `object_storage_
  configured == True` and a real upload/exists/download roundtrip
  against the actual `ecolense` R2 bucket (not MinIO). Re-ran ML
  training (all 4 models) and a real ingest afterward — both confirmed
  landing in real R2 (`s3://ecolense/models/anomaly/*.joblib`,
  `s3://ecolense/staging/*.duckdb`), not local MinIO.
- **Anomaly detection**: real, and now genuinely **hybrid** —
  rule-based bounds checks (`_BOUNDS`) + a per-batch z-score
  (`_Z_SCORE_THRESHOLD`) + a per-source `IsolationForest` ML signal
  (`app/service/pipeline/ml_anomaly.py`), all three combined by taking
  the worst per row (`anomaly.py`'s `_Winner`), persisted to `meta.
  anomalies`. **2026-08-05 — real models now trained and live** for all
  4 backfillable sources (`oe`, `aemo-nem`, `aemo-wem`, `bom` —
  `holidays` has no numeric columns, never gets one) against real
  accumulated history, each individually calibrated (a real
  miscalibration bug was found and fixed the same day — see "Remaining
  Work" §2 for the full story). A source's ML signal reverts to `None`
  (no contribution, 2-signal fallback) if its model is ever missing —
  e.g. a fresh environment before `ecolens-ingestion train-anomaly-
  model <source>` has been run at all.
- **Circuit breaker**: real, Redis-backed (`app/service/pipeline/
  circuit_breaker.py`).
- **APIs**: `GET/PATCH /v1/data-sources[/{id}]`, `.../health`,
  `.../history`, `POST .../run`, `POST .../backfill`, `GET .../
  backfill/status`; `POST /v1/ingest/{source}` (synchronous); `POST
  /v1/ingest/{source}/backfill` (`202` + `backfill_id`, backgrounded —
  2026-08-05, was synchronous), `GET /v1/ingest/{source}/backfill/
  status`; `GET /v1/ingestion/runs/{id}`; `GET /v1/healthz`,
  `/v1/readyz`, `/metrics`. All open — no auth required for now (`app.
  core.security`/`app.core.ratelimit` exist, real and tested, just not
  wired into any route).
- **The shared Neon database's `meta`/`raw`/`ml`/`analytics` schemas**
  were found missing earlier and have been restored (idempotent
  migrations re-applied) — no longer a blocker for anything below. This
  has recurred more than once (a fresh/rebranched Neon database with no
  schemas at all, most recently 2026-08-05 after `DATABASE_URL` was
  repointed to a different Neon project) — `services/data-pipeline/
  scripts/apply-migrations.sh` is idempotent and safe to re-run whenever
  this happens again; skip `0020_recover_legacy_openelectricity.sql`
  specifically (a real, known Postgres `AND`-short-circuit bug, its own
  docstring confirms skipping is correct).
- **Local DuckDB staging retention**: real (`app/service/pipeline/
  retention.py`, `ecolens-ingestion prune-staging`) — see "Remaining
  Work" §3.

---

## Remaining Work

### 1. Ingestion Pipeline Mechanism — Celery-based scheduled dispatch

**Update 2026-08-05 — implemented, live-verified against real
infrastructure.** Broker/backend decision: RabbitMQ-as-broker
(`Settings.rabbitmq_url`, already a hard dependency), Redis-as-result-
backend (`Settings.redis_url`, already used for the circuit breaker) —
both existing services, no new infrastructure.

[x] Add Celery as a dependency + an app instance (`app/celery_app.py`).
    `celery>=5.4` added — pulled in `amqp`/`kombu`'s own pure-Python
    AMQP transport as a transitive dependency, so RabbitMQ-as-broker
    works with no extra broker-client package. `mypy` override added
    for `celery.*` (no published type stubs, same pattern as
    `croniter.*`/`aioboto3.*`).
[x] Wrap `pipeline.tasks.registry.run_source` in a Celery task —
    `app/service/pipeline/tasks/celery_tasks.py`'s `ingest_source_task`,
    a thin `asyncio.run(run_source(...))` bridge (Celery's task-
    execution model is sync, `run_source` is async), not a rewrite. No
    Celery-level retry — a failed run is already recorded in `meta.
    _ingest_log` (`status="failed"`) and the next Beat tick picks the
    source back up on its own regular cadence; a second, uncoordinated
    retry mechanism on top would race the circuit breaker's own
    backoff logic.
[x] **Update 2026-08-05 — replaced with one unified 30-minute Beat
    entry for all 5 sources**, per explicit request ("add cron job to
    fetch data in every 30 min", resolved via `AskUserQuestion` to:
    a new Beat entry, not GitHub Actions; all 5 sources on one shared
    cadence, not per-source). `app/celery_app.py`'s `beat_schedule` now
    has a single `"ingest-all-sources"` entry (`crontab(minute="*/30")`)
    calling a new `ingest_all_sources_task`
    (`app/service/pipeline/tasks/celery_tasks.py`), which fans out to
    each `registry.SOURCES` key as an independent `celery.group` child
    (`ingest_source_task.si(key, ...)`) rather than one sequential
    in-process loop — so one slow/hung source still can't hold up the
    others, same "resilient, decoupled" property the earlier per-source
    design also had. This **replaces**, not supplements, the earlier
    5-entry per-source-cadence schedule (`oe` every 5 min, `aemo-nem`/
    `aemo-wem` every 15, `bom` every 30, `holidays` annually) that was
    briefly implemented and tested before this change.
    **Known, accepted tradeoff**: `oe`'s real ~5-minute update frequency
    and `aemo-nem`/`aemo-wem`'s ~15-minute frequency are no longer
    matched — all sources are now polled at a uniform 30-minute cadence,
    reducing data freshness for the higher-frequency sources in exchange
    for one simple, uniform schedule. (The Beat-vs-GitHub-Actions
    question this originally left open is resolved — see the last item
    in this section.)
[x] Worker + beat scheduler processes — `infra/docker/ingestion.
    Dockerfile` changed from a fixed `CMD ["uvicorn", ...]` to
    `ENTRYPOINT ["ecolens-ingestion"]` + `CMD ["serve"]` (same pattern
    data-pipeline's own Dockerfile already uses for its `worker`/
    `train-worker` services), so `docker-compose.yml`'s new `ingestion-
    worker` (`command: worker --loglevel=info`) and `ingestion-beat`
    (`command: beat --loglevel=info`) services can override just the
    subcommand. `docker compose config --quiet` validates clean.
[x] `ecolens-ingestion` CLI gains `worker`/`beat` commands —
    `celery_app.start(["worker", *extra_args])`/`["beat", *extra_args]`,
    extra args pass straight through (`--loglevel=info`, etc.), same
    role `serve` already plays for the FastAPI app. Live-verified: both
    commands actually start a real Celery worker/beat process connected
    to real local RabbitMQ + Redis (not just "doesn't crash on
    `--help`").
[x] Tests: task wiring (mocked `run_source`, success/failure/default-
    kwargs), beat schedule contents (single unified entry, correct
    30-min cadence, correct fan-out task name, `triggered_by="schedule"`,
    no positional `args`), `ingest_all_sources_task`'s fan-out (one
    `celery.group` child per registry source, each targeting
    `ingest_source_task`, each source key covered exactly once,
    `triggered_by` defaulting correctly — via `_FakeGroup`/
    `_FakeGroupResult` helpers that capture real `.si()` signatures
    without needing a broker), broker/backend URL config, CLI
    `worker`/`beat` passthrough. **Broker connection health is not
    folded into `/v1/readyz`** — deliberately deferred, not forgotten:
    `/v1/readyz` already checks the same RabbitMQ connection Celery's
    broker uses (`get_rabbitmq_connection`), so a second, separate
    Celery-specific check would be redundant against the identical
    underlying connection.
    - **Real, live end-to-end verification** (not just unit tests):
      started a real worker (`uv run celery -A app.celery_app worker`)
      against real local RabbitMQ + Redis, confirmed it registered both
      tasks and connected to both. Dispatched a real
      `ingest_all_sources_task.delay(triggered_by="manual")`, confirmed
      via `.get(timeout=15)` that it returned 5 child task ids, and
      confirmed via the worker's own log that all 5 real registry
      sources (`oe`, `aemo-nem`, `aemo-wem`, `bom`, `holidays`) were
      received and started as independent child tasks — confirming the
      full fan-out pipeline (Beat → `ingest_all_sources_task` → 5×
      `ingest_source_task` children → `run_source` → real ingest logic)
      works correctly end to end. **308 tests passing, `ruff check`/
      `ruff format --check`/`mypy app`/`mypy scripts` all clean.**
    - **Update 2026-08-06 — actually running now, not just verified
      once.** Earlier verification started a worker/beat pair, tested
      it, then stopped it — nothing was left running. `ecolens-
      ingestion worker --loglevel=info` (8 prefork children) and
      `ecolens-ingestion beat --loglevel=info` are now both genuinely
      up in this environment, connected to real RabbitMQ/Redis. Manually
      dispatched `ingest_all_sources_task.delay(triggered_by="manual")`
      against the *live* worker (not a throwaway test one) — confirmed
      all 5 real sources received and completed (`aemo-nem`: 30 rows
      staged, `aemo-wem`: 1 row staged, etc.) via the worker's own log.
      Beat will fire the same task on its own every 30 minutes from
      here on, unattended, for as long as these two processes stay up.
[x] **Update 2026-08-05 — resolved.** The drafted, never-enabled GitHub
    Actions cutover workflows (`.github/workflows/ingest-*-ingestion-
    service.yml` — `oe`/`aemo`/`bom`/`holidays`, all `workflow_dispatch`-
    only) have been deleted (they were untracked, never committed — no
    git history lost). Celery Beat is the settled scheduler for this
    service. Note this is separate from `data-pipeline`'s own *legacy*
    per-source `ingest-{source}.yml` workflows, which are real,
    currently-live `schedule:`-triggered cron and untouched by this —
    those go away only once Phase 6 (decommission legacy `data-pipeline`
    ingestion code, "Also still open" below) actually happens.

### 2. Anomaly Detection Layer — the ML half of "hybrid"

**Update 2026-08-05 — implemented.** Model approach decided: an
`IsolationForest` per source (not a seasonal-residual baseline — both
were reasonable starting points per this section's original note; this
one was chosen as the more standard, more "real ML" starting point,
accepting the extra moving parts — a training job, model artifact
versioning, an explicit retraining trigger — that a seasonal-residual
baseline wouldn't have needed).

[x] Model approach: an `IsolationForest` per source
    (`app/service/pipeline/ml_anomaly.py`), trained over whatever
    numeric columns `anomaly._NUMERIC_COLUMNS` already scans for that
    source — same column set both the rule-based/z-score signals and
    the ML signal look at, not a separate feature list to keep in sync.
    `holidays` (no numeric columns configured) never gets a model, same
    as it never gets the other two signals.
[x] `app/service/pipeline/ml_anomaly.py` — `train`/`save_local`/
    `load_local`/`score`/`train_and_publish`, plus an in-process
    `_CACHE` so a worker process loads a given source's model from disk
    at most once, not once per ingest batch.
[x] Training data source: `pipeline.duckdb_staging.read_table_history`
    — the shared `landed.duckdb` file's full accumulated per-source
    history, genuinely queryable for this specifically *because* staging
    moved off one-file-per-run. `ml_anomaly.MIN_TRAINING_ROWS` (50, a
    deliberately generous starting threshold) real historical rows are
    required before `train` fits anything — below that, `train` returns
    `None` (skipped, not an error) rather than persist a model that's
    mostly noise.
[x] Model artifact persistence: `ml_anomaly.upload_model` reuses
    `app.service.object_storage` (R2, local MinIO fallback) — a fixed
    `models/anomaly/{source}.joblib` key per source (always overwritten
    on retrain, unlike a staged run's unique-per-run key). This is what
    "all artefacts (including model weights) end up in Cloudflare R2"
    means in practice — no new storage mechanism, just a new artifact
    type through the existing one.
[x] Combined via `anomaly.py`'s existing `_Winner` "take the worst of
    the signals" pattern, as a genuine third signal, not a parallel
    flagging system — `detect_anomalies` now lazily imports `ml_anomaly`
    (avoids a circular import; `ml_anomaly` imports `_NUMERIC_COLUMNS`
    from `anomaly` at its own top level) and folds `ml_anomaly.score`'s
    per-row output in alongside the rule-based/z-score checks, only
    when it clears `ml_anomaly.ANOMALY_SCORE_THRESHOLD` (`None` — no
    model trained yet for a source — leaves existing 2-signal behaviour
    completely unchanged, confirmed by every pre-existing `test_
    anomaly.py` test still passing unmodified).
[x] **Update 2026-08-05 (same day, later) — a real calibration bug was
    found and fixed** while training the first real models against
    actual accumulated history (not synthetic test data). The original
    `score()` used `0.5 - score_samples` clipped to `[0, 1]`, assuming
    `score_samples`' natural baseline sits near 0 — true-ish on the
    tightly-clustered synthetic data unit tests used, **false on real
    `aemo_nem_dispatch` history**: real `score_samples` sat tightly
    around **-0.49**, so that formula scored *every* row (normal and
    anomalous alike) at ~0.98-0.99, clearing any fixed threshold —
    the ML signal was flagging almost everything, not a rare/meaningful
    subset. Confirmed directly by inspecting real `score_samples`/
    `decision_function` output against real trained-on data before
    accepting the result as correct.
    **Fix**: `score()` now uses `IsolationForest.decision_function`
    (sklearn's own already-offset measure) rescaled onto `[0, 1]`
    relative to **each model's own training distribution** — `train`
    now also stores `decision_threshold` (the `1`st percentile of the
    training set's own `decision_function` values — "rarer than 99% of
    this source's real history") and `decision_floor` (the most extreme
    training value, for scaling) per model, not one universal constant
    across every source. `ANOMALY_SCORE_THRESHOLD` changed from `0.55`
    to `0.3` (a row must clear 30% of the threshold→floor gap, not just
    barely cross the calibration boundary). Added `tests/test_ml_
    anomaly.py::TestScore::test_does_not_flag_plausible_values_from_a_
    widely_spread_history` — deliberately wide/varied training data
    (unlike the tight synthetic cluster the other tests use) to catch
    this exact class of bug on any future scoring-formula change.
    **Verified against all 4 real trained models** (`oe`, `aemo-nem`,
    `aemo-wem`, `bom` — `holidays` has no numeric columns, never gets
    one), each source's own training data now flags at
    **0.07%-0.67%**, a sane, low baseline rate (comparable to the
    z-score signal's own inherent false-positive rate at its threshold),
    not the ~99% the broken version produced.
[x] **Update 2026-08-05 — real models trained and live in this
    environment.** `ecolens-ingestion train-anomaly-model {oe,aemo-nem,
    aemo-wem,bom}` run against the real accumulated shared-`landed.
    duckdb` history (thousands of real rows per source, collected
    across this session's live testing) — all 4 uploaded successfully
    (confirmed via `object_storage.object_exists`; retrained again after
    real R2 credentials were added the same day, now genuinely landing
    in `s3://ecolense/models/anomaly/*.joblib`, not local MinIO — see
    Ground Truth's own R2 note). The ML signal is now genuinely active
    for
    any ingest run against this local environment, not just present in
    code — confirmed live via `anomaly.detect_anomalies` directly
    against a synthetic implausible row (30000 MW demand, -950 $/MWh
    price), correctly flagged at score `1.0`, `metric=demand_mw`
    (rule-based `out_of_range` wins that particular row on a `1.0 ==
    1.0` tie — `_Winner.consider`'s strict `score > self.score` means
    whichever check runs first keeps a tie, and rule-based checks run
    before the ML check in `detect_anomalies`'s per-row loop) with
    `ml_outlier:isolation_forest` still recorded in `anomaly_reason`
    alongside it either way.
[x] Retraining trigger: **manual/CLI-triggered**
    (`ecolens-ingestion train-anomaly-model <source>`), *not* a Celery
    Beat schedule — the conservative option between the two this
    section's original note left undecided. An operator/cron outside
    this service decides when to retrain, rather than this shipping with
    an unreviewed automatic retraining schedule from day one. Wiring a
    periodic Beat entry later (once real retraining-cadence needs are
    known, e.g. weekly/monthly) is a small, additive follow-up on top of
    this, not a redesign — **still an open decision**, deliberately not
    resolved here.
[x] Tests: `tests/test_ml_anomaly.py` (train/skip thresholds, save/load
    roundtrip, scoring against a real fitted forest including a genuine
    multivariate outlier, missing-column handling, cache behaviour,
    `train_and_publish`'s upload + cache-invalidation), `tests/
    test_anomaly.py`'s new `TestMLSignal` class (integration: `None`
    leaves behaviour unchanged, a high score flags a row the other two
    signals missed, the worse-of-three combine in both directions).
    `tests/test_cli.py`'s new `TestTrainAnomalyModelCommand`.
[x] **Update 2026-08-06 — done.** `meta.anomalies` gains
    `rule_based_score`/`statistical_score`/`ml_score` (all nullable
    `numeric`, migration `0025_anomalies_signal_scores.sql`, applied
    live against the real shared Neon database — confirmed via `\d
    meta.anomalies`) — one column per signal category, independent of
    `_Winner`/`anomaly_score`/`metric`, which still only ever record the
    single *worst* signal (unchanged, still the right design for "the
    headline flag"). NULL means that signal didn't fire for the row;
    non-NULL is that signal's own score, even when it didn't win. A row
    flagged by both rule-based and ML (e.g. `"out_of_range:demand_mw=
    -50; ml_outlier:isolation_forest(score=0.81)"`) now has both
    `rule_based_score=1.0` and `ml_score=0.81` queryable directly,
    instead of only recoverable by parsing `anomaly_reason`'s free-text
    string. `detect_anomalies` tracks each category's own max score
    per row alongside the existing `_Winner`; `record_anomalies`
    persists all three. `services/data-pipeline`'s own copy of the
    detector (frozen legacy 2-signal version, predates the ML signal)
    is untouched — the new columns are nullable, so its inserts are
    unaffected. Tests: `tests/test_anomaly.py` extended (per-signal
    score assertions on every existing case, plus explicit "both
    signals fired, only one wins the headline slot" coverage).

### 3. Storage — close the loop on the event-driven warehousing side

Most of "Storage" is already real (see Ground Truth). What's left was
finishing the handoff to the warehouse side, not the staging/R2
mechanism itself.

[x] **Update 2026-08-05 — `data-pipeline`'s `warehouse_sync` consumer
    fixed.** `pipeline.duckdb_staging.read_staged`/`delete_staged`
    (`services/data-pipeline`'s own copy) now take `(path, table,
    run_id)`, matching `services/ingestion`'s producer-side signature —
    the RabbitMQ payload already carried `table`/`run_id`, the consumer
    just wasn't using them yet. Handles **both** on-disk shapes that can
    now show up under the same payload structure: this service's own
    still-active legacy one-file-per-run producer (fixed `landed` table
    — tried first, cheapest, still the common case) and `services/
    ingestion`'s newer shared-file producer (falls back to reading the
    real per-source `table`, `_ingest_run_id`-filtered, only if `landed`
    isn't present). `warehouse_sync.sync_landed_event` updated to pass
    the new args through; `test_duckdb_staging.py`/`test_warehouse_
    sync.py` updated + extended with a new `TestSharedFileShape` class.
    **733 data-pipeline tests passing**, `ruff`/`mypy` clean.
    Note (verified 2026-08-05, while chasing what looked like a related
    bug during live local testing): `docker-compose.yml` mounts the same
    named `duckdb_staging` volume into each service's container at
    `<its own WORKDIR>/data/staging` — `Settings.duckdb_staging_dir`'s
    default (`"./data/staging"`, relative) resolves against each
    container's own `WORKDIR`, so both containers land on the *same*
    physical file despite the payload's `duckdb_path` being a relative
    string, not an absolute one. Confirmed by reading both Dockerfiles'
    `WORKDIR`s + the compose volume mounts directly, not assumed. A
    bare local, non-Docker dev setup running both processes from
    mismatched working directories will *not* see the same file this
    way (confirmed the hard way, live, earlier this session) — a real,
    already-understood limitation of testing this specific handoff
    outside Docker, not a bug in the fix above or in `duckdb_staging_
    dir` staying relative.
[x] **Update 2026-08-05 — local retention policy implemented.**
    `app/service/pipeline/retention.py`'s `prune_synced_history`:
    deletes local shared-file rows for runs that are both `meta.
    _ingest_log.status = 'success'` (durably synced to Postgres — R2
    already has its own durable copy earlier still, before a run ever
    reaches `'staged'`) *and* older than `retention.
    DEFAULT_RETENTION_DAYS` (a plain, easily-changed module constant —
    deliberately generous to start, not tuned against real observed disk
    growth yet; raised from 14 to **30** on 2026-08-06, per explicit
    request). `'staged'`/`'sync_failed'` runs are never
    touched — still exactly the recovery-artifact contract `pipeline.
    duckdb_staging`'s own docstring documents. Manually/cron-triggered
    (`ecolens-ingestion prune-staging [--days N]`), not a Celery Beat
    schedule — same conservative default `ml_anomaly`'s retraining
    trigger uses, for the same reason. `delete_staged`'s return type
    changed from `None` to `int` (rows actually deleted) so `prune_
    synced_history` can report a real per-source summary — confirmed
    unused elsewhere in this service before making that change. Tests:
    `tests/test_retention.py`.
[ ] **Not done this pass, deliberately left documentation-only**: R2
    lifecycle policy (expiry/tiering) for `staging/*` objects, which
    still accumulate one snapshot per run indefinitely with no pruning.
    Recommended concrete policy, not yet applied: expire objects under
    `staging/` after `retention.DEFAULT_RETENTION_DAYS` (currently 30,
    kept in sync with the local pruning policy above) via a bucket
    lifecycle rule — R2 supports this natively (Cloudflare dashboard or
    the S3-compatible lifecycle API), no application code required. Not
    applied here because it's a live change against the real R2 bucket
    config, not a code change `services/ingestion` itself owns or can
    safely make unattended.
[x] **Update 2026-08-07 — the consumer side of this handoff is now
    real, not just this producer's own upload.** This section's own
    Ground Truth already documented that `upload_staged_file` uploads
    every run to object storage and `publish_landed_event` carries
    `object_storage_key`/`_bucket` alongside `duckdb_path` — but until
    now, **neither consumer actually read those fields.**
    `services/data-pipeline`'s `warehouse_sync.sync_landed_event` and
    `services/waerehouse`'s `consumers.landed_events.sync_landed_event`
    both only ever read the local `duckdb_path`, meaning the shared
    `duckdb_staging` Docker volume this repo's `docker-compose.yml`
    happens to mount into all three containers was silently doing 100%
    of the real work — the object-storage fields were dead data as far
    as consumption went, and running `services/ingestion` on a
    different machine than its consumer would have either raised on a
    missing file or (worse, `services/waerehouse`'s own `read_run`)
    silently synced **zero rows** as if nothing was wrong. Fixed both
    consumers: `data-pipeline`'s new `duckdb_staging.
    read_staged_with_fallback` and `waerehouse`'s new `duckdb_client.
    read_run_with_fallback` try the local file first (same-host fast
    path, unchanged), then download+read the run's object-storage
    snapshot when it's missing. `services/waerehouse`'s own
    `db/object_storage.py` gained `download_bytes` (it was upload-only
    before — "nothing in this service ever reads cold-storage exports
    back" was true of cold-storage specifically, not of this new
    staging-snapshot read path). See `docs/runbooks/independent-
    service-deployment.md` for the operational requirement this
    creates (real R2 credentials, not local MinIO, are now required —
    not just convenient — on both sides once ingestion and its
    consumer are on different machines). 9 new tests across both
    consumer services, `data-pipeline` full suite (749 passed/5
    skipped, same 1 pre-existing unrelated failure) and `waerehouse`
    full suite (83 passed/1 skipped) both green, `ruff`/`mypy` clean on
    every changed file.

---

## Also still open from before (unaffected by the above)

[ ] **Phase 4 (shadow verification)**: tooling is real and tested
    (`triggered_by="shadow"` routing, `scripts/verify_shadow_parity.py`)
    but has never been run against a real multi-hour window — needs
    live deployment time, not more code.
[ ] **Phase 5 (live cutover)**: **Update 2026-08-05 — the mechanism
    changed.** The per-source `workflow_dispatch`-only GitHub Actions
    cutover drafts this item originally pointed at have been removed
    (Remaining Work §1) — Celery Beat (`ingest-all-sources`, every 30
    min, all 5 sources) is the real scheduler now. "Cutover" is
    therefore no longer "flip a workflow's trigger to `schedule:`" —
    it's enabling/relying on the `ingestion-worker`/`ingestion-beat`
    docker-compose services (or their real-deployment equivalent) as
    the production source of truth for a given source, in place of
    `data-pipeline`'s own still-live per-source cron. Still needs a real
    shadow-window result (Phase 4, above) and the user's explicit
    per-source go-ahead first — not a coding task.
[ ] **Phase 6 (decommission legacy `data-pipeline` ingestion code)**:
    not started; blocked on Phase 5 actually happening for real first.
