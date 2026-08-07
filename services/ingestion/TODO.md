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
  item. The *legacy* per-source `ingest-{source}.yml` workflows were, at
  the time this note was first written, described here as "real,
  currently-live" — **that was never actually verified against GitHub
  and turned out to be false** (Phase 5's 2026-08-07 update, below):
  they existed only on the local `dev` branch, were never merged to
  `main`, and GitHub's own workflow API confirms they were never
  registered — meaning they never fired on a schedule. Removed
  2026-08-07 (Phase 6) — see that section for the full finding.
- **Real per-source cadences** (`app/models/datasources.py`'s
  `CATALOG`, already correct — not literally "5 and 30 minutes" for
  everything): `oe` every 5 min, `aemo-nem`/`aemo-wem` every 15 min,
  `bom` every 30 min, `holidays` once a year. **Note (2026-08-07):**
  this is what the `CATALOG` metadata *says* each source's real-world
  cadence is — it is no longer what Celery Beat actually *dispatches*
  at (see the byte-sized breakdown's "Cadence mismatch" item below).
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
- **OE backfill (2026-08-07)**: the full historical `openelectricity_
  mix` gap (2025-08-01 → present) is now closed — every day landed, 0
  duplicate rows. Found and fixed a real O(n²) bug in the third-party
  `openelectricity` SDK's `TimeSeriesResponse.to_records()` along the
  way (it linearly rescans every record built so far, calling
  `.isoformat()` each time, for every point — made later-month days
  take 30-60+ min instead of ~1-2s once a region's fueltech-grouping
  count grew large enough). Patched with an O(n) dict-keyed drop-in
  replacement, monkeypatched onto the SDK class in `app/service/
  emissions.py` — same output shape, confirmed ~35s for a day that
  previously took 30-60 min. This fix benefits *all* OE fetches going
  forward (live ingestion included), not just backfill.
- **`aemo_nem_dispatch`**: effectively complete. One permanent,
  confirmed-real upstream gap on `2026-03-10` (AEMO's own archive only
  has 1,335/1,440 rows for that day — re-fetching returns the same
  count, not something this service can fix).
- **`aemo_wem_dispatch`**: complete, no known gaps besides the two
  expected range-boundary edges (start of backfill range, today).
- **`bom_observations`**: complete for what the data source can
  provide. Historical backfill sources from Open-Meteo's ERA5
  reanalysis archive (`ingest_bom.py`), which is **hourly-resolution
  data** — the visibly "low" row counts across most of the historical
  range (144/day = 24/station × 6 stations) are the ceiling of that
  archive, not a fetch gap. Live ingestion still captures BOM's real
  5-minute cadence going forward.
- **`aemo_holidays`**: 2025 + 2026 both fetched and deduplicated (a
  stray, out-of-range 2030 batch from an earlier fetch was found and
  removed 2026-08-07).

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
    - **Update 2026-08-07 — no longer running.** Checked this session:
      no `celery worker`/`beat` process is alive in this environment
      right now (RabbitMQ/Redis themselves are up, nothing is
      dispatching on schedule). Whatever was running 2026-08-06 didn't
      survive past that session. See the byte-sized breakdown below for
      the concrete restart steps — this needs a real restart policy,
      not just remembering to start it by hand each session.
[x] **Update 2026-08-05 — resolved.** The drafted, never-enabled GitHub
    Actions cutover workflows (`.github/workflows/ingest-*-ingestion-
    service.yml` — `oe`/`aemo`/`bom`/`holidays`, all `workflow_dispatch`-
    only) have been deleted (they were untracked, never committed — no
    git history lost). Celery Beat is the settled scheduler for this
    service. This note originally described `data-pipeline`'s own
    *legacy* per-source `ingest-{source}.yml` workflows as "real,
    currently-live `schedule:`-triggered cron" — **turned out to be
    false, never actually verified against GitHub** (Phase 5's
    2026-08-07 update). Those 4 files are now removed (Phase 6,
    2026-08-07) — see that section for the full finding.

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
    this, not a redesign — **still an open decision** — see the
    byte-sized breakdown below for the concrete steps.
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

## What's left — byte-sized breakdown (2026-08-07, updated same day)

Everything below was previously written as big, vague phases ("Phase 5:
live cutover"). Re-cut into pieces small enough to actually pick up and
finish in one sitting. Most of it got done the same day it was written —
see each item's own update note for what actually happened, live.

### Quick housekeeping

[x] **Fix a stale comment.** `docker-compose.yml`'s `ingestion-beat`
    service comment now says what's actually true (unified 30-min
    schedule, 2026-08-05) instead of the old per-source cadence it used
    to describe.
[x] **Give `ingestion-worker`/`ingestion-beat` a restart policy.**
    `restart: unless-stopped` added to both in `docker-compose.yml`.

### Get it actually running again

[x] **Started the worker + beat pair, bare-metal (not docker-compose,
    to match the real credentials/local Redis+RabbitMQ already in this
    environment).** Hit two real bugs getting there, both fixed:
    - **RabbitMQ 4.x / Celery incompatibility.** The worker crash-looped
      with `RestartFreqExceeded` — root cause: `amqp.exceptions.
      InternalError: Queue.declare: (541) INTERNAL_ERROR - Feature
      'transient_nonexcl_queues' is deprecated`. RabbitMQ 4.x disabled a
      transient-queue pattern Celery's kombu/amqp transport still uses.
      `--without-mingle --without-gossip` did *not* fix it (base
      consumer setup hits the same deprecated path, not just mingle).
      Fixed server-side with RabbitMQ's own documented transition flag:
      `/opt/homebrew/etc/rabbitmq/rabbitmq.conf` now has
      `deprecated_features.permit.transient_nonexcl_queues = true`
      (note the real key is `deprecated_features.permit.$name`, *not*
      `deprecated_feature_flags.permit.$name` — got this wrong first,
      RabbitMQ's own boot error told us the right one). `brew services
      restart rabbitmq` to apply. Local-dev-only fix; a real deployed
      RabbitMQ would need the same conf line or a Celery/kombu version
      that's dropped the deprecated pattern.
    - **A real DuckDB single-writer race, found live.** Once the worker
      connected, `aemo-nem` and `bom` both failed on the very first
      scheduled tick with `duckdb.IOException: Could not set lock on
      file "landed.duckdb"... Conflicting lock is held`.
      `ingest_all_sources_task`'s whole design point is fanning all 5
      sources out as independent parallel `celery.group` children so one
      slow source can't block the others — the direct, previously-
      unnoticed cost of that is real concurrent writers racing DuckDB's
      single read-write lock on the shared staging file. Fixed in
      `app/service/pipeline/duckdb_staging.py`: a new
      `_connect_rw_with_retry` (jittered exponential backoff, 5
      attempts) wraps every real-write `duckdb.connect` call
      (`stage_dataframe`, `merge_staging_file`, `delete_staged`) —
      catches specifically the "Conflicting lock" `IOException` and
      retries; any other `IOException` still raises immediately. Live-
      confirmed the fix: killed and restarted the worker with the patch,
      redispatched, `aemo-nem`/`bom` (the two that failed before) both
      landed cleanly this time, all 5 sources `status='staged'`. Tests:
      `tests/test_duckdb_staging.py::TestConnectRwWithRetry` (4 new
      cases — successful retry, exhausts-then-raises, a non-lock
      `IOException` isn't retried, and a real concurrent-write scenario
      through `stage_dataframe` itself, not just the connect wrapper in
      isolation). 359+ tests passing, `ruff`/`mypy` clean.
[x] **Confirmed it's really dispatching.** Live end-to-end: Beat fired
    `ingest-all-sources` on its own, the worker picked it up, all 5
    sources landed (`meta._ingest_log` rows with `triggered_by=
    'schedule'`/`'manual'`, `status='staged'`, real row counts). Both
    processes are running right now in this environment as of this
    update — same "was verified once, then silently stopped" risk
    2026-08-06 hit still applies the moment this session ends; the
    restart-policy fix above only helps once these run under `docker
    compose`, not as bare background processes in a terminal.

### Decide: cadence mismatch — kept as-is, documented instead of reverted

[x] **Decision: keep the unified 30-minute schedule.** Not reverted to
    per-source cadence — that was already an explicit, deliberate
    2026-08-05 decision (via `AskUserQuestion`), and reversing an
    already-made product tradeoff isn't something to do silently as a
    side effect of a cleanup pass. Documented instead: the Ground
    Truth section's "Real per-source cadences" bullet now has an
    explicit 2026-08-07 note that `CATALOG`'s per-source cadence
    numbers describe intent, not what Beat actually dispatches at. If
    the per-source cadence should come back after all, that's still a
    real, undone task — see this section's original note on why it
    means writing new `beat_schedule` entries from scratch, not
    reverting a commit (the earlier version was never committed).

### Phase 4 — shadow verification: reliability confirmed, real bug found and fixed along the way

[x] **Ran a same-day smoke test for all 4 backfillable sources**
    (`ecolens-ingestion ingest <source> --triggered-by shadow`, then
    `scripts/verify_shadow_parity.py --source <source> --from 2026-08-07
    --to 2026-08-07 --against manual`). `bom` matched cleanly
    (`shadow=6, manual=6, 0.0% delta`); `oe`/`aemo-nem`/`aemo-wem` all
    came back trivially `0/0`.
[x] **Update 2026-08-07 (same day, later) — found and fixed the real
    bug behind that `0/0`, and the original diagnosis above (`window_start`
    filtering) was wrong.** Re-examined the script directly instead of
    trusting the earlier guess: `_collect()` actually filters on
    `started_at`, not `window_start` — that part was fine. The real bug:
    `_verify()` passed the raw `--source` CLI value (a registry key —
    `"oe"`, `"aemo-nem"`, `"aemo-wem"`) straight into `_collect`'s
    `WHERE source = :source`, but `meta._ingest_log.source` stores
    `registry.SOURCES[key].source` — `"openelectricity"`, `"aemo_nem"`,
    `"aemo_wem"`, genuinely different strings. `bom`'s key and `.source`
    value are identical by coincidence, which is exactly why it alone
    "just worked" and every pre-existing test (all written against
    `"bom"`) never caught this class of bug. **Fixed**: `_verify` now
    resolves `SOURCES[source].source` once before querying. Added
    `tests/test_verify_shadow_parity_script.py::
    test_verify_queries_meta_ingest_log_source_not_the_registry_key`
    (parametrized over all 4 sources — fails against the old code for 3
    of them, passes for `bom` only by the same accident the real bug
    had). **Re-ran the same smoke test live against the fix**: all 4
    sources now show real, matching comparisons (`oe`: 19 vs 20 rows,
    5% delta; `aemo-nem`: 30/30; `aemo-wem`: 1/1; `bom`: 6/6 — all within
    tolerance). 16/16 script tests passing, `ruff`/`mypy` clean.
[x] **Update 2026-08-07 — the real multi-hour bake window is running.**
    Launched a detached background loop (`nohup`, survives this session)
    firing `triggered_by="shadow"` ingests for all 4 backfillable
    sources every 30 minutes (matching the real `schedule` cadence) for
    6 hours, logging to `scratchpad/shadow_bake.log`.
[x] **Update 2026-08-07 (same day, later) — the bake's own comparison
    surfaced a real, serious reliability bug, found and fixed across
    three escalating rounds before Phase 4 could be considered
    genuinely passed.** Running `verify_shadow_parity.py --against
    schedule` on the partial (~1h43m) accumulated window showed *every*
    source's `schedule`-triggered group full of `'failed'` runs —
    `RuntimeError: Event loop is closed`. Root cause, found the hard way
    across three rounds because each fix revealed the next:
    - **Round 1 (Postgres)**: `app.db.session.get_engine` is
      `@lru_cache`'d — a real, process-lifetime connection pool — but
      `celery_tasks.py` called `asyncio.run(...)` per task, which
      destroys its event loop when the task finishes. The pool later
      tried to recycle a connection from a dead loop and raised.
      "Fixed" by disposing the engine at the end of every task
      (`_run_and_dispose_engine`) — confirmed clean on the *next single
      tick*, which turned out to be a false negative (see below).
    - **Round 2 (Redis)**: a live 8-run rapid-dispatch stress test
      (compressing multiple "ticks" into minutes instead of passively
      waiting 30 min each) showed the *same* error, now inside the
      Redis client's `read_response` — `app.db.redis.get_redis` has the
      identical `@lru_cache` pattern, just not covered by round 1's
      fix. Extended the same per-task-dispose approach to cover both
      (`_run_and_dispose_shared_clients`).
    - **Round 3 (RabbitMQ) — the fix that revealed this needed a
      different kind of solution entirely.** A harder rapid-dispatch
      stress test (5 dispatches, 25 task executions) showed **19 of 25
      still failing** — this time inside `app.db.rabbitmq.
      get_rabbitmq_connection`'s module-level global `_connection`, a
      *third* independent instance of the same underlying pattern.
      Whack-a-mole patching resource-by-resource had no defined end —
      R2's `aioboto3.Session()` happened to already be safe (confirmed:
      not cached, fresh per call), but there was no principled reason to
      believe RabbitMQ would be the last one either.
    **Fixed at the root instead of patched per-client**: `app.
    celery_app` now creates **one persistent event loop per forked
    Celery worker process** (`worker_process_init` signal), reused for
    every task that process ever runs via a new `run_async(coro)` —
    `celery_tasks.py`'s replacement for calling `asyncio.run()`
    directly. Every process-lifetime-cached client now genuinely gets
    the process lifetime it already assumed it had; disposal moved from
    "after every single task" to "once, at real worker shutdown"
    (`worker_process_shutdown` signal), which is when it always should
    have run. Removed the now-unnecessary per-task dispose wrapper
    entirely — this isn't additive on top of rounds 1-2, it replaces
    them.
    **Live-verified, not just reasoned through**: restarted the worker,
    ran **8 rapid dispatches (40 total task executions across all 5
    sources)** back to back — confirmed via direct `meta._ingest_log`
    query: **40/40 `status='staged'`, zero failures**, versus 19/25
    failing under the previous (incomplete) fix run the same way minutes
    earlier. Also triggered fresh `shadow` runs against the now-fixed
    worker — clean. Tests: `tests/test_celery_app.py::TestRunAsync` (4
    cases — falls back to a fresh `asyncio.run()` outside a worker
    process, uses/reuses the persistent loop when one exists, doesn't
    try to reuse an already-closed leftover loop) and `::
    TestWorkerProcessLifecycleSignals` (3 cases — init creates a real
    loop, shutdown closes it and disposes both clients, shutdown is a
    no-op if init never ran), plus `tests/test_celery_tasks.py::
    TestUsesRunAsyncNotAsyncioRunDirectly` (2 cases, replacing the
    now-obsolete per-round dispose tests). **414 tests passing**,
    `ruff`/`mypy` clean.
    **The `verify_shadow_parity.py`/`--from`/`--to` CLI is day-
    granularity only** — it can't cleanly isolate an intra-day
    before/after-the-fix window, so a same-day script-driven comparison
    still mixes in this morning's now-fixed failures. Went around it
    with a direct SQL query scoped to the exact post-fix timestamp
    instead (`started_at >= '2026-08-07 10:35:00+00'`): **40/40 manual
    + 4/4 shadow, zero failures, real matching row counts across all
    5/4 sources.** That's the real Phase 4 evidence — the day-level
    script output above should be read as "confirms the plumbing
    works," not "the system is reliable"; this direct-query result is
    what actually confirms reliability. Worth a follow-up: teach the
    script an hour-level `--from`/`--to` so this manual workaround isn't
    needed again.

### Phase 5 — live cutover: the premise this phase was scoped against turned out to be false

[x] **Update 2026-08-07 — checked before touching anything, per this
    section's own long-standing caution, and found the whole "cutover"
    framing needs to be reconsidered, not just executed.** Phase 4
    (above) is now genuinely, verifiably passed — that part of the
    prerequisite is real. But before disabling the "legacy live cron"
    this section always pointed at
    (`.github/workflows/ingest-{openelectricity,aemo,bom,holidays}.yml`),
    checked whether it's actually live, rather than trusting this file's
    own repeated prior description of it as "real, currently-live" —
    that description was never actually verified against GitHub itself
    at any point this session, only against the files' presence in the
    local working tree.
    **It isn't live.** Confirmed three independent ways:
    1. `git ls-tree -r origin/main --name-only | grep workflows/ingest`
       — **empty**. These 4 files exist only on the local `dev` branch
       (1 commit ahead, 22 behind `origin/main`), never merged.
    2. GitHub's own default branch for this repo is `main`
       (`api.github.com/repos/diptu/EcoLens`) — and GitHub Actions
       `schedule:` triggers only ever fire for workflow files that
       exist *on the default branch*. A workflow only present on a
       feature branch is inert, regardless of what its own YAML says.
    3. `api.github.com/repos/diptu/EcoLens/actions/workflows` — GitHub's
       actual registered-workflow list — contains exactly 5 workflows
       (`ci.yml`, `docker.yml`, `main.yml`, `ml-pipeline.yml`,
       `release.yml`). **None of the 4 ingest workflows appear at all.**
       They've never been registered, meaning they've never fired on a
       schedule, meaning there is no "legacy live cron" for this phase
       to cut over *from*.
    Also checked whether `data-pipeline` triggers ingestion via any
    *other* live mechanism (its own worker process, some deployed
    scheduler outside GitHub Actions) — `docker-compose.yml` only
    defines `data-pipeline` (the API server) and `train-worker` (model
    training, unrelated); no ingestion-scheduling process exists there
    either.
    **What this actually means**: there is no real production ingestion
    cron running anywhere right now, for any source, on either service.
    `services/ingestion`'s own Celery Beat (this session's work) is
    already the *only* live, scheduled ingestion path that exists —
    which is arguably a bigger finding than "Phase 5 is done": there was
    never a real competing system to "cut over" away from. "Disable the
    legacy cron" (this section's original task) is now moot, not
    completed — nothing to disable.
    **Not resolving the deeper question this raises, on purpose**: was
    `data-pipeline`'s ingestion *ever* live in production, or was that
    always aspirational/planned and this file's repeated "real,
    currently-live" framing was itself never checked against the truth?
    That's a real question about this project's actual production
    history that only you can answer — not something to guess at or
    resolve unilaterally. If `data-pipeline`'s ingestion truly never ran
    in production, `services/ingestion` may already be the de facto
    (if informal) system of record, and "Phase 5" may really just mean
    "merge the `ingest-*.yml` question closed" plus the frontend wiring
    (below) — a much smaller task than originally scoped. If it *was*
    live at some point through a mechanism this check didn't find,
    that needs surfacing before anything else proceeds.
[ ] **Newly discovered 2026-08-07 (frontend analysis, see the new
    section below): "cutover" as scoped above is backend-only and
    doesn't cover the dashboard.** `services/dashboard` has zero
    awareness `services/ingestion` exists — flipping the backend switch
    alone would leave the dashboard still reading `data-pipeline`,
    showing no visible change to a user. Read the "Frontend
    integration" section below before treating Phase 5 as "cutover
    done" even after the backend half lands.

### Phase 6 — decommission legacy `data-pipeline` ingestion code

[x] **Update 2026-08-07 — the dead-cron half done; the code half
    deliberately NOT done, scope corrected before touching anything.**
    This phase's original text said "remove `data-pipeline`'s per-source
    ingest task code" — written under the assumption (Phase 5's finding
    corrects this) that the only thing keeping that code alive was a
    cron cutover. **Checked before deleting anything and found that
    assumption was wrong**: `data-pipeline/app/service/datasources/
    actions.py` (backing the live, tested `POST /v1/data-sources/{id}/
    run` — the exact endpoint `services/dashboard`'s "Trigger data
    ingestion pipelines" button and `lib/ingestion.ts`'s
    `triggerIngestionRun` call, confirmed real this session) calls the
    *same* `app.service.pipeline.tasks.registry.run_source` the dead
    cron would have called. **Deleting that code would have broken a
    real, working, dashboard-facing feature that has nothing to do with
    the cron question.** Not a hypothetical risk — traced the exact
    call site before deciding, not assumed either way.
    **Done**: removed the 4 confirmed-dead workflow files (`.github/
    workflows/ingest-{openelectricity,aemo,bom,holidays}.yml` — per
    Phase 5's finding, never merged to `main`, never registered on
    GitHub, never fired). Also removed `docs/runbooks/github-actions-
    secrets.md` — its entire content was secret-configuration
    instructions for those same 4 dead workflows, not referenced from
    anywhere else, no purpose left once they're gone. Corrected two
    earlier passages in this file's own Ground Truth/§1 sections that
    still asserted the legacy cron was "real, currently-live" (written
    before Phase 5's check — left as historical record with a
    correction note appended, not silently rewritten).
    **Not done**: `data-pipeline`'s actual ingest task Python code
    (`registry.py`, `ingest_openelectricity.py`, `ingest_aemo_nem.py`,
    etc.) — still genuinely in use via the live HTTP API, staying
    exactly as-is. If/when a real frontend cutover happens (the
    "Frontend integration" section below) and the dashboard stops
    calling `data-pipeline` for triggers/backfills too, *that* would be
    the point where this code becomes genuinely dead and safe to
    remove — not before. `git rm` used (not a bare delete) for
    everything removed this pass, so it's a normal, revertible
    (`git revert`/`git checkout`) change, not a bare filesystem
    deletion — not committed (this session's own consistent practice
    throughout — the user commits).

### Anomaly retraining automation

[x] **Implemented, weekly, Sunday 02:00 UTC.** `app/service/pipeline/
    tasks/celery_tasks.py` gains `train_anomaly_model_task` (same
    thin-wrapper shape as `ingest_source_task`, calls `ml_anomaly.
    train_and_publish`) and `train_all_anomaly_models_task` (same
    `celery.group` fan-out shape as `ingest_all_sources_task`, one child
    per `pipeline.backfill.BACKFILLABLE_SOURCES` key — `holidays`
    excluded, same reason it never gets a model at all). New
    `retrain-all-anomaly-models` entry in `app.celery_app`'s
    `beat_schedule`. **Sunday 02:00 UTC is a deliberate default, not a
    tuned cadence** — a real decision this section always said was
    needed; change the one `crontab(...)` if it turns out wrong.
    A skipped retrain (`train_and_publish` returns `None` — not enough
    accumulated history yet) now logs at `warning` with an explicit
    reason instead of vanishing silently. A real training failure still
    raises (visible in Celery's own task-failure tracking), same as
    `ingest_source_task`'s existing behavior. Tests: `tests/
    test_celery_tasks.py::TestTrainAnomalyModelTask`/
    `TestTrainAllAnomalyModelsTask` (8 new cases), `tests/
    test_celery_app.py::TestRetrainAnomalyModelsBeatSchedule` (3 new
    cases) — caught one real bug along the way (`log.info(...,
    source=key, **summary)` collided because `summary` already has its
    own `source` key; fixed by dropping the redundant explicit one).

### R2 lifecycle policy

[x] **Update 2026-08-07 (same day, later) — applied, per explicit
    request/authorization** ("proceed, store 2 month worth data in R2
    only" — after the environment's own safety classifier first blocked
    this same action unattended, correctly, since it's a live change
    against the real production `ecolense` bucket; this went ahead only
    once a human explicitly said so in direct response to that
    explanation, not by working around the block).
    **Retention set to 60 days (2 months), not `retention.
    DEFAULT_RETENTION_DAYS` (30)** — deliberate, per the request's own
    wording ("R2 only"): R2 is the durable long-term artifact copy,
    local DuckDB staging is short-lived scratch space cleaned by
    `prune-staging` — there's no requirement these two match, and a
    longer R2 window is the more conservative direction to diverge in
    (local rows can be pruned once safely synced to Postgres; R2's own
    copy staying around longer costs nothing that local pruning
    depends on). Confirmed current state before touching anything (one
    pre-existing, unrelated rule — `Default Multipart Abort Rule`,
    7-day incomplete-multipart cleanup — no `staging/*` expiry existed
    yet), applied via `s3.put_bucket_lifecycle_configuration` (the same
    `aioboto3`/R2-credentials path `app/service/object_storage.py`
    already uses), preserving the existing rule (`put_bucket_lifecycle_
    configuration` replaces the whole ruleset, not merges). **Read back
    immediately after applying** (`get_bucket_lifecycle_configuration`)
    to confirm the new rule's `Filter` really is scoped to `staging/`
    before trusting it — a wrong prefix here would be a real, live
    data-loss risk against a bucket real model artifacts (`models/
    anomaly/*.joblib`) also live in. Confirmed both rules present,
    `expire-staging-snapshots-60d` correctly filtered to `staging/`
    only, `Days: 60`.
[x] Left a note in `retention.py` (see below) pointing at this R2 rule
    and its deliberately-different 60-day window, so a future edit to
    `DEFAULT_RETENTION_DAYS` doesn't assume the two are supposed to
    match.

---

## Frontend integration — a real gap Phase 5/6 never covered (2026-08-07)

Analyzed `services/dashboard` (the real Next.js frontend, not a mock —
confirmed by reading `src/lib/env.ts`, `src/lib/ingestion.ts`,
`src/lib/health.ts`, `src/lib/data-quality.ts`, and the actual page
components directly) to find what "remaining ingestion work" looks like
from the consumer side, not just the backend. One headline finding, plus
three concrete downstream ones — all traced to real code, not assumed.

**Headline finding: the dashboard doesn't know `services/ingestion`
exists.** Its known backends are exactly three (`src/lib/env.ts`:
`IAM_API_URL`, `FORECAST_API_URL`, `DATA_PIPELINE_API_URL` — no fourth
`NEXT_PUBLIC_INGESTION_API_URL` anywhere, confirmed by grepping the whole
`src/lib` tree). Every ingestion-related page (`/dashboard/ingestion`,
`/dashboard/data-sources`, `/dashboard/data-quality`,
`/dashboard/operational-tasks`) talks exclusively to `data-pipeline` —
the *legacy* system this whole file's Phase 5/6 is about replacing.
`docker-compose.yml` already runs `services/ingestion`'s own FastAPI app
on port 8003 (confirmed: `ingestion:` service block, `ports: ["8003:8003"]`,
real `/v1/healthz` healthcheck) — the dashboard just has no configured
way to reach it. This means Phase 5 "cutover" as originally scoped
(above) only ever covered *which backend produces the data*, never
*which backend the dashboard reads from* — two different problems that
were being treated as one.

### Concrete downstream gaps this causes, right now (not hypothetical)

[x] **Update 2026-08-07 — fixed.** `src/lib/env.ts` gains
    `INGESTION_API_URL` (port 8003, matching `docker-compose.yml`'s real
    `ingestion:` service). `src/lib/health.ts` gains
    `fetchIngestionHealth()` — confirmed live that `services/ingestion`'s
    `/v1/readyz` returns the exact same `{status, components}` shape
    `data-pipeline`'s does (same three checks: Postgres, Redis,
    RabbitMQ — just no MLflow, this service has none), so parsing is a
    straight copy of `fetchDataPipelineHealth`'s. Wired into
    `fetchAllServicesHealth()` — the one real consumer turned out to be
    `/dashboard/operations` (`lib/health.ts`'s own docstring calling out
    "3 services" was accurate for *that* module; `/dashboard/
    system-health` is a separate page reading from `lib/admin.ts`'s
    synthetic data instead, unaffected by this fix — see the next item).
    `ServiceHealth.service` union type extended to include `"ingestion"`.
    The operations page's list rendering is fully generic
    (`servicesHealth.map((s) => ...)`, keyed on `s.service`) — the new
    entry needed zero page-level UI changes, just showed up. Verified:
    `npx tsc --noEmit` and `npx vitest run` both show zero new failures
    (pre-existing, unrelated breakage in `auth.test.ts`/
    `pricing-data.test.ts` only — different modules, confirmed by name).
    **Found and fixed a second, more serious bug while doing this**: the
    root `.gitignore`'s Python-boilerplate `lib/` entry (no leading
    slash) was silently matching `services/dashboard/src/lib/` too —
    `health.ts` (before this edit even existed) and `data-quality.ts`
    were **untracked and at real risk of silent loss** on a fresh clone
    or `git clean`. Confirmed `.venv` is already separately ignored and
    Python's `build/lib/` is already covered by the `build/` rule, so
    the bare `lib/` line was pure redundant boilerplate actively eating
    real source — removed it, not re-scoped. Both files now show as
    untracked (`??`) instead of invisible; **not staged or committed**
    (this session's own consistent practice — the user commits), but
    flagged clearly so they don't get lost before that happens.
[ ] **The real hybrid anomaly detection has no display path anywhere.**
    The one page that looks like it should show this
    (`src/lib/admin.ts`'s "anomaly-detection page" data layer) is
    **entirely synthetic** — its own docstring: "In production this
    calls the admin-api (`http://localhost:8004`)... For the dashboard
    demo (no admin-api service attached yet) we generate deterministic,
    realistic data with a seeded PRNG." That `admin-api` service doesn't
    exist anywhere under `services/` (port 8004 in `docker-compose.yml`
    is actually `waerehouse`, unrelated) — this page was built against a
    planned service that was never built, not against real ingestion
    data. Meanwhile `services/ingestion`'s `meta.anomalies` has real,
    live, per-signal scores (`rule_based_score`/`statistical_score`/
    `ml_score`) from a calibrated 3-signal detector, verified working
    this session. Two independent problems bundled into one: (a) no
    `admin-api` service exists to build this page against yet — out of
    this file's scope, that's a dashboard/platform decision, not an
    ingestion one; (b) *separately*, `services/ingestion`'s Data Quality
    page (`fetchPublicDataQualitySummary`) currently reads
    `data-pipeline`'s `/v1/data-quality/summary/public`, which is backed
    by "`services/data-pipeline`'s own copy of the detector (frozen
    legacy 2-signal version, predates the ML signal)" (Remaining Work §2
    above) — so even the one real, live KPI on the dashboard reflects
    the *old*, un-recalibrated 2-signal detector, not the work done in
    §2 of this file. Whichever service ends up authoritative post-Phase-5
    needs to also become what this KPI reads from.
[x] **Update 2026-08-07 (same day, later) — built.** Re-read `data-
    pipeline`'s real implementation once more and decided this service's
    own version didn't need every one of its features (no pause/resume
    to report — `services/ingestion` has no such mechanism at all, so
    `enabled` is honestly always `True` rather than faked; no separate
    dbt-build pipeline; `id`/`source_id` reuse this service's own
    existing `ds-*` catalog ids from `app.models.datasources.CATALOG`,
    already what `GET /v1/data-sources/{id}` uses, not a new scheme).
    New: `app/schemas/ingest/public.py` (response models),
    `app/service/public_pipelines.py` (`list_pipelines_public`/
    `list_runs_public`), two new routes on the *existing*
    `app/api/v1/ingestion/routes.py` router — `GET /v1/ingestion/
    public/pipelines`, `GET /v1/ingestion/public/runs` (cursor-paginated
    via a base64-encoded offset, same shape data-pipeline's identical
    endpoint uses).
    **Schedule field reports the real Beat cadence (`*/30 * * * *`), not
    `CATALOG[].cron`'s aspirational per-source one** — deliberately
    chosen to not repeat the exact doc-says-X-reality-is-Y problem this
    file's own Ground Truth section already had to call out once.
    No Redis response caching (data-pipeline's version has one) — no
    real traffic yet to justify it; every query here is already a single
    indexed scan, not the kind of aggregation caching earns its keep
    for. Add it later if a real load profile asks for it.
    **Live-verified end to end, not just unit-tested**: started a real
    `ecolens-ingestion serve` process, `curl`'d both endpoints over real
    HTTP against the live Neon database — `public/pipelines` correctly
    returned all 5 real catalog sources with real 24h stats (`oe`:
    346 runs, 95.7% success, real `p95_duration_ms_24h`); `public/runs`
    correctly returned real, current `meta._ingest_log` rows, cursor
    pagination working (`total: 2265`). Also hit `/v1/readyz` the same
    way to confirm the dashboard health-check fix above is pointed at a
    route that's actually live and correctly shaped.
    **Found something unrelated while live-testing, confirmed out of
    scope**: real `POST /v1/data-sources/ds-bom/run` calls
    (`triggered_by="public"`, a pre-existing hardcoded value in
    `app/api/v1/datasources/routes.py`, nothing to do with this work)
    are landing every 5-10 minutes from something external to this
    session, bursts of 5 at a time, `bom` only. Confirmed this service's
    own two new endpoints are 100% read-only (grepped `public_
    pipelines.py` for INSERT/UPDATE/DELETE — none) before ruling it out
    as a cause. Not investigated further — real, but unrelated to
    anything in this file.
    Tests: `tests/test_public_pipelines_service.py` (12 cases — all 5
    catalog sources present, the real-cadence-not-catalog-cron
    assertion, null stats for a source with no runs, success-rate
    treating `staged` as non-failure, `ds-*` id mapping, no leaked
    `error`/`hostname`/`metadata` fields, `duplicates_skipped`
    arithmetic, pagination `has_more`/`next_cursor` both directions,
    `source_id` filter resolution including an unknown-id case, a
    malformed-cursor fallback), `tests/test_public_pipelines_router.py`
    (5 cases — no-auth-required, real 5-source response, query-param
    handling, a 422 on an out-of-range `limit`). 388 tests passing
    (`ruff`/`mypy` clean) as of this update.
[x] **Update 2026-08-07 (same day, still later) — a second real bug
    found and fixed while live-testing the above, unrelated to the new
    endpoints themselves.** Beat's regular tick started failing across
    *all 5 sources simultaneously* with `RuntimeError: Event loop is
    closed`, first observed live via `meta._ingest_log`. Root cause:
    `app.db.session.get_engine` is `@lru_cache`'d — a real, module-level
    singleton whose SQLAlchemy connection pool survives across every
    `asyncio.run()` call in the same forked Celery worker child, but
    each `celery_tasks.py` task calls `asyncio.run(...)` fresh, which
    fully destroys its event loop when the coroutine returns. When the
    pool later tried to recycle a connection opened under a *previous*
    task's now-dead loop, asyncpg's cleanup path called `loop.
    create_task(...)` against that closed loop and raised. This is a
    real production reliability bug independent of anything else this
    session touched — it would keep recurring on whatever cadence the
    pool decides to recycle connections, for as long as the worker
    process stays up. **Fixed**: `celery_tasks.py` gains
    `_run_and_dispose_engine`, a small wrapper that disposes the
    engine's pool (`app.db.session.dispose`, already existed for FastAPI
    shutdown, just never called from here) at the end of every task —
    under the *same* event loop `asyncio.run()` created for that task,
    before it's destroyed — so the *next* task always starts against a
    fresh pool instead of a connection tied to a dead loop. Wired into
    both `ingest_source_task` and `train_anomaly_model_task` (the two
    real `asyncio.run()` call sites). **Live-confirmed the fix**:
    restarted the worker, manually dispatched `ingest_all_sources_task`
    against it — all 5 sources landed cleanly (`staged`/`running`, zero
    failures) on the first tick after the fix. Can't be proven fully
    eliminated in one tick alone (the original bug needed some real
    elapsed time / pool-recycling condition to trigger) — worth
    continuing to watch `meta._ingest_log` for any further "Event loop
    is closed" occurrences, but the fix is the standard, correct
    remedy for this exact, well-documented class of bug (SQLAlchemy
    async engine + repeated `asyncio.run()` in a long-lived process).
    Tests: `tests/test_celery_tasks.py::TestEngineDisposal` (4 cases —
    both tasks, both the success and the failure path, confirming
    dispose is awaited in every case via `finally`, not just the happy
    one). **395 tests passing** (full suite, confirmed), `ruff`/`mypy`
    clean across the whole service.

### What this means for sequencing

Phase 5 (above) needs a frontend half added to its own definition, not
just a backend one: even a fully successful backend cutover leaves the
dashboard reading stale (`data-pipeline`) data until someone (a) builds
the missing public/aggregate endpoints on `services/ingestion`, (b)
wires `NEXT_PUBLIC_INGESTION_API_URL` + a 4th health check into
`services/dashboard`, and (c) repoints `lib/ingestion.ts`/
`lib/data-quality.ts` at the new endpoints. None of this is started —
recorded here because it's real, traceable-to-code scope Phase 5 didn't
previously account for, not because it needs to happen before the
backend work above.

---

## Independent-microservice readiness pass (2026-08-07)

Triggered by verifying `POST /v1/data-sources/{id}/run` end to end
before recommending it as a `data-pipeline` replacement — the endpoint
already existed (full data-pipeline-equivalent, confirmed field-for-
field schema match with `services/dashboard`'s `RunTrigger` TypeScript
type), but live-testing it surfaced real gaps that only show up once
you actually try to run this service standing alone.

### 1. Structural dependency on `data-pipeline` — fixed

[x] **`_already_in_flight` (`app/service/datasources/actions.py`)
    treated `status IN ('running', 'staged')` as blocking, with no time
    bound, by design** — a deliberate choice ported from `data-
    pipeline`'s identical check. The problem: `staged` only ever
    resolves to `success` via `data-pipeline`'s own `warehouse_sync`
    consumer, which lives in a *different service*. Confirmed live:
    `aemo_wem` alone had **497 rows stuck at `staged`, only 2 at
    `success`**, because nothing in this environment consumes the
    RabbitMQ events to finalize them. Consequence: `POST .../run`
    becomes permanently unusable for any source after its first
    successful fetch, in any deployment where this service runs without
    that consumer alongside it — i.e. genuinely not independently
    deployable as shipped.
    **Fixed**: `running` keeps its original no-timeout behavior
    (deliberately — a truly in-progress fetch shouldn't be raced by a
    duplicate). `staged` now gets a real, documented time bound
    (`_STAGED_STALE_AFTER = timedelta(hours=1)`) — recent enough to
    still respect a healthy consumer's normal processing time, but no
    longer capable of blocking forever. Tests: `tests/
    test_datasource_actions_router.py::
    TestAlreadyInFlightStagedStaleness` (5 cases — running blocks
    regardless of age, recent staged blocks, stale staged doesn't,
    success/failed never block, no rows never blocks).
[x] **132 orphaned `running` rows corrected** (separate from the above
    — these were `running`, not `staged`, left over from this session's
    own repeated process kills during live debugging, 2026-08-05
    through -07). Confirmed every one was genuinely abandoned (newest
    was 6 hours old, every process since restarted multiple times)
    before correcting — done only after explicit go-ahead, since it's a
    direct data mutation against the live production database.

### 2. Errors were silently unloggable — fixed

[x] **A real 500 came back with an empty logged error message**
    (`error=""`) while live-testing the trigger endpoint under
    concurrent load. Root cause: both exception handlers (`app/main.py`
    and `app/core/middleware.py` — there are two, deliberately, for a
    documented `BaseHTTPMiddleware` exception-propagation gap) logged
    `error=str(exc)` — empty for some real exception types (e.g. a bare
    `asyncio.TimeoutError()`), making a real production incident
    undebuggable from logs alone. **Fixed**: both now log
    `exc_info=exc` instead — structlog's already-configured `format_
    exc_info` processor renders the full exception type + traceback
    from that, not just whatever `str()` happens to produce.
    The specific 500 that surfaced this didn't reliably reproduce once
    system load settled (consistent with transient connection-pool
    pressure, see below) — the logging fix stands regardless of that
    one incident's exact cause, since the empty-message failure mode is
    real and independent of what actually caused any given 500.

### 3. No explicit connection pool limits — fixed

[x] **`app/db/session.py`'s `get_engine()` had no explicit `pool_size`/
    `max_overflow`/`pool_timeout` at all** — SQLAlchemy's defaults
    (5 + 10 = 15 max connections) applied *per process*, and this
    service now genuinely runs as several independent processes against
    the same Neon database at once (FastAPI server + an 8-child-prefork
    Celery worker, each with its own `@lru_cache`'d engine post the
    event-loop fix above) — worst case, ~135 possible connections from
    this service alone. Likely, if not certainly, related to the
    transient 500 above. **Fixed**: explicit, conservative
    `pool_size=2, max_overflow=3, pool_timeout=10, pool_recycle=300` —
    small per-process footprint, fails fast (10s) instead of hanging
    the default 30s+ on exhaustion, and recycles connections Neon may
    have silently dropped server-side. Tests: `tests/test_session.py::
    test_get_engine_has_conservative_explicit_pool_sizing`.

**398 tests passing** (full suite), `ruff`/`mypy` clean, as of this
update.

### Still open — genuinely deferred, not forgotten

[ ] Whether `services/ingestion` should grow its *own* `warehouse_sync`
    consumer (removing the `data-pipeline` dependency entirely) or
    whether the 1-hour staleness bound above is an acceptable permanent
    answer is a real architecture decision, not resolved here — the fix
    above makes the endpoint *usable* independent of that decision, it
    doesn't make the coupling disappear.
[ ] The transient 500's *exact* root cause wasn't conclusively
    reproduced under the improved logging — the pool-sizing fix is the
    most likely remedy (and a real improvement regardless), but if a
    similar 500 recurs, the new `exc_info=exc` logging will now show
    the real exception type/traceback instead of an empty string.
