/**
 * data-pipeline client — ingestion/pipelines domain.
 *
 * Talks to the real, currently-live `/v1/ingestion/*` + `/v1/data-sources/*`
 * routes (`services/data-pipeline/app/api/v1/{pipelines,datasources}/routes.py`)
 * — verified directly against a running instance, not assumed from source
 * reading alone (earlier versions of this file guessed at a contract that
 * didn't exist yet; that's no longer true, confirmed via the live OpenAPI
 * schema and an actual triggered run).
 *
 * Read endpoints use the unauthenticated `/public/*` mirrors — genuinely
 * public projections (see each one's own docstring in pipelines/routes.py),
 * not a stripped-down summary.
 *
 * `triggerIngestionRun` (`POST /v1/data-sources/{id}/run`) is deliberately
 * open too — no bearer token required. Triggering a pipeline run isn't a
 * privileged action in this platform's current scope; the backend's
 * `require_roles("admin")` gate on this route was removed for exactly this
 * reason (see that route's own comment).
 */

import { DATA_PIPELINE_API_URL } from "./env";

export type PipelineStage = "extract" | "transform";
export type LivePipelineStatus = "active" | "paused";

/** Shape of data-pipeline's `PipelineOut`. */
export type LivePipeline = {
  id: string;
  name: string;
  source_id: string | null;
  stage: PipelineStage;
  status: LivePipelineStatus;
  schedule: { cron: string; timezone: string; enabled: boolean };
  depends_on: string[];
  last_run_at: string | null;
  next_run_at: string | null;
  run_count_24h: number;
  success_rate_24h: number | null;
  p95_duration_ms_24h: number | null;
};

/** Shape of data-pipeline's `PipelinesListResponse`. */
export type PipelinesList = {
  meta: { total: number; active: number; paused: number; as_of: string };
  data: LivePipeline[];
};

export async function fetchPublicPipelines(): Promise<PipelinesList> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/ingestion/public/pipelines`);
  if (!res.ok) {
    throw new Error(`GET /v1/ingestion/public/pipelines failed: ${res.status}`);
  }
  return res.json();
}

/** Static — mirrors `data-pipeline`'s own `app/models/datasources.py`
 * `CATALOG` (5 real sources; a new one only ever shows up here after a
 * matching code change on the ingestion side too). `PipelineOut` only
 * carries `source_id`, not a display name, so this is the minimal lookup
 * needed to show something better than a raw "ds-aemo-nem" id. */
const SOURCE_LABELS: Record<string, string> = {
  "ds-oe": "OpenElectricity",
  "ds-aemo-nem": "AEMO NEM",
  "ds-aemo-wem": "AEMO WEM",
  "ds-bom": "Bureau of Meteorology",
  "ds-holidays": "AEMO Public Holidays",
};

export function formatSource(sourceId: string | null): string {
  if (sourceId == null) return "dbt (warehouse transform)";
  return SOURCE_LABELS[sourceId] ?? sourceId;
}

export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin} min ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr} hr ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay} day${diffDay === 1 ? "" : "s"} ago`;
}

/** Same idea as `formatRelativeTime` but for a *future* timestamp
 * (`LivePipeline.next_run_at`) — not interchangeable with it, since
 * "X min ago" logic on a future time would misreport it as already
 * overdue. */
export function formatTimeUntil(iso: string): string {
  const diffMs = new Date(iso).getTime() - Date.now();
  const diffMin = Math.round(diffMs / 60_000);
  if (diffMin <= 0) return "due now";
  if (diffMin < 60) return `in ${diffMin} min`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `in ${diffHr} hr`;
  const diffDay = Math.round(diffHr / 24);
  return `in ${diffDay} day${diffDay === 1 ? "" : "s"}`;
}

export type PipelineHealth = "success" | "failed" | "paused" | "idle";

/** `PipelineOut.status` (active/paused) is an on/off switch, not a "did
 * the last run succeed" signal. Derives the closest honest health signal
 * from what's actually here: paused wins outright, then 24h success
 * rate, then "idle" when there's nothing to judge (no runs in the
 * window) rather than pretending "queued"/"running" when neither is
 * observable at this endpoint's granularity. */
export function derivePipelineHealth(p: LivePipeline): PipelineHealth {
  if (p.status === "paused") return "paused";
  if (p.success_rate_24h == null) return "idle";
  return p.success_rate_24h >= 100 ? "success" : "failed";
}

/** Static — mirrors `data-pipeline`'s `app/models/pipelines.py` `PIPELINES`
 * catalog (6 real pipelines: 5 ingestion sources + the dbt-warehouse
 * build). `source_id` is `null` for the warehouse build — it's a dbt
 * run, not an ingestion fetch, so it has no matching `/data-sources/*`
 * entry and can't be triggered via `triggerIngestionRun`; its own
 * `triggerable: true` below routes through `triggerDbtBuild()` instead
 * (TODO.md's backfill section — this is the manual escape hatch for a
 * dashboard-triggered backfill never refreshing `raw_marts.*` on its
 * own). */
export type PipelineCatalogEntry = {
  id: string;
  sourceId: string | null;
  label: string;
  triggerable: boolean;
  /** Whether `POST /v1/data-sources/{id}/backfill` actually fetches real
   * data for the requested historical range, not just a rolling "last
   * 24h from now" window repeated once per day in the range (see
   * `pipeline/backfill.py`'s `backfill_day`/`_DATE_RANGE_SOURCES` —
   * `aemo_nem`/`aemo_wem`/`bom`/`oe` have a real date-anchored fetch;
   * `holidays`'s backfill would silently re-fetch today's data N times
   * instead of the actual requested days, so the UI doesn't offer it for
   * that one). `bom` joined this list 2026-08-05 — BoM's own API has no
   * date-range query at all (only a rolling ~72h window), so
   * `ingest_bom.py` now sources real historical weather from
   * Open-Meteo's ERA5 archive instead for exactly this path. `oe` joined
   * the same day — `ingest_openelectricity.py`'s `_fetch_historical_range`
   * now targets a real day via OE's own `network_region`/`date_start`/
   * `date_end` params instead of always meaning "last N minutes from
   * now" (the OE region-join blocker fix, `todo-model-training.md`). */
  backfillable: boolean;
};

export const PIPELINE_CATALOG: PipelineCatalogEntry[] = [
  { id: "pipe-aemo-nem", sourceId: "ds-aemo-nem", label: "AEMO NEM Ingest", triggerable: true, backfillable: true },
  { id: "pipe-aemo-wem", sourceId: "ds-aemo-wem", label: "AEMO WEM Ingest", triggerable: true, backfillable: true },
  { id: "pipe-bom", sourceId: "ds-bom", label: "Bureau of Meteorology Ingest", triggerable: true, backfillable: true },
  { id: "pipe-oe", sourceId: "ds-oe", label: "OpenElectricity Ingest", triggerable: true, backfillable: true },
  { id: "pipe-holidays", sourceId: "ds-holidays", label: "AEMO Public Holidays Ingest", triggerable: true, backfillable: false },
  { id: "pipe-dbt-warehouse", sourceId: null, label: "dbt Warehouse Build", triggerable: true, backfillable: false },
];

const PIPELINE_LABELS: Record<string, string> = Object.fromEntries(
  PIPELINE_CATALOG.map((p) => [p.id, p.label]),
);

export function formatPipeline(pipelineId: string): string {
  return PIPELINE_LABELS[pipelineId] ?? pipelineId;
}

// ────────────────────────────────────────────────────────────────────
// Runs — GET /v1/ingestion/public/runs
// ────────────────────────────────────────────────────────────────────

export type RunStatus =
  | "success" | "failed" | "running" | "staged" | "sync_failed" | "queued" | "partial";

/** Shape of data-pipeline's `PublicRunOut` — `RunOut` minus `error`
 * (raw exception text) and `metadata` (carries an internal hostname). */
export type PublicRun = {
  id: string;
  pipeline_id: string;
  source_id: string;
  status: RunStatus;
  trigger: string;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  records_fetched: number | null;
  records_inserted: number | null;
  duplicates_skipped: number | null;
  anomalies_flagged: number | null;
};

export type PublicRunsList = {
  meta: { total: number; filtered: number };
  data: PublicRun[];
  next_cursor: string | null;
  has_more: boolean;
};

export async function fetchPublicRuns(limit = 12, sourceId?: string): Promise<PublicRunsList> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (sourceId) params.set("source_id", sourceId);
  const res = await fetch(`${DATA_PIPELINE_API_URL}/ingestion/public/runs?${params}`);
  if (!res.ok) {
    throw new Error(`GET /v1/ingestion/public/runs failed: ${res.status}`);
  }
  return res.json();
}

// ────────────────────────────────────────────────────────────────────
// Triggering a run — POST /v1/data-sources/{id}/run
// ────────────────────────────────────────────────────────────────────

/** Shape of data-pipeline's `RunTriggerResponse`. 202 — the fetch is
 * handed off to a background task, not awaited; `run_id` is a synthetic
 * trigger id, not the run's real DB id (that row doesn't exist yet at
 * response time — poll `fetchPublicRuns(1, sourceId)` for the actual
 * outcome, not this response). */
export type RunTrigger = {
  run_id: string;
  source_id: string;
  status: "queued";
  queued_at: string;
  estimated_start_at: string;
  priority: "low" | "normal" | "high";
  triggered_by: string;
  reason: string | null;
  deduplicate: boolean;
  force: boolean;
};

export class TriggerIngestionError extends Error {
  constructor(
    message: string,
    public status: number,
    public code: string | null,
  ) {
    super(message);
    this.name = "TriggerIngestionError";
  }
}

/** Live call to `POST /v1/data-sources/{sourceId}/run` — `sourceId` is
 * the data-source catalog id (`PIPELINE_CATALOG[].sourceId`, e.g.
 * "ds-aemo-nem"), not the pipeline id ("pipe-aemo-nem") — the dbt
 * warehouse-build pipeline has `sourceId: null` and can't be triggered
 * this way at all (it's a dbt build, not an ingestion fetch).
 *
 * No auth required — this route is deliberately open (see this file's
 * module docstring). A fresh `crypto.randomUUID()` per call as the
 * idempotency key means a network retry of the *same* click can't
 * double-trigger a run; two separate clicks each get their own key and
 * both go through (by design — this is a manual "run now" action, not
 * a form submit that should collapse duplicates).
 *
 * `force: true` bypasses the circuit breaker (lets a run through even
 * if the source is currently marked broken) — real, but deliberately
 * not exposed as a casual one-click option; callers should ask for
 * confirmation before setting it. */
export async function triggerIngestionRun(
  sourceId: string,
  opts?: { force?: boolean; reason?: string },
): Promise<RunTrigger> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "Idempotency-Key": crypto.randomUUID(),
  };
  if (opts?.reason) headers["X-Reason"] = opts.reason;

  const res = await fetch(`${DATA_PIPELINE_API_URL}/data-sources/${sourceId}/run`, {
    method: "POST",
    headers,
    body: JSON.stringify({ force: opts?.force ?? false, deduplicate: true }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message: string =
      body?.error?.message ?? `POST /v1/data-sources/${sourceId}/run failed: ${res.status}`;
    throw new TriggerIngestionError(message, res.status, body?.error?.code ?? null);
  }
  return res.json();
}

// ────────────────────────────────────────────────────────────────────
// Backfilling a real historical range — POST /v1/data-sources/{id}/backfill
// ────────────────────────────────────────────────────────────────────

/** Shape of data-pipeline's `BackfillTriggerResponse`. `chunk` is
 * accepted and reported back but execution is always real
 * day-granularity underneath (`pipeline.backfill.backfill`) — see that
 * module and `PIPELINE_CATALOG[].backfillable`'s docstring for which
 * sources this is genuinely real for. */
export type BackfillTrigger = {
  backfill_id: string;
  source_id: string;
  status: "queued";
  queued_at: string;
  start: string;
  end: string;
  chunk: string;
  concurrency: number;
  deduplicate: boolean;
  total_chunks: number;
  estimated_duration_seconds: number;
  triggered_by: string;
  progress_url: string;
};

/** First-day-00:00Z through last-day-00:00Z of `yearMonth` (an
 * `<input type="month">` value, `"YYYY-MM"`) — matches
 * `pipeline.backfill.daterange`'s inclusive-both-ends semantics
 * exactly (verified against a real trigger: `end` at the last day's
 * *start*, not the first of the next month, gives exactly that
 * month's days, no more) — get this backwards and the backfill either
 * misses the last day or spills one day into the next month. */
export function monthToRange(yearMonth: string): { start: string; end: string } {
  const [year, month] = yearMonth.split("-").map(Number); // month: 1-12
  const start = new Date(Date.UTC(year, month - 1, 1));
  const end = new Date(Date.UTC(year, month, 0)); // day 0 of `month` = last day of the previous (target) month
  return { start: start.toISOString(), end: end.toISOString() };
}

/** `start === end`, both `date`'s own 00:00Z (an `<input type="date">`
 * value, `"YYYY-MM-DD"`) — matches `pipeline.backfill.daterange`'s
 * inclusive-both-ends semantics exactly like `monthToRange` does for a
 * month: `daterange(day, day)` yields exactly that one day, no more, no
 * less. Separate function rather than reusing `monthToRange` with a
 * same-month/same-day pair — the input shape (`"YYYY-MM-DD"`, not
 * `"YYYY-MM"`) is genuinely different, not just a narrower range. */
export function dayToRange(date: string): { start: string; end: string } {
  const [year, month, day] = date.split("-").map(Number);
  const start = new Date(Date.UTC(year, month - 1, day));
  return { start: start.toISOString(), end: start.toISOString() };
}

/** Shape of data-pipeline's `BackfillStatusResponse` — the live state
 * behind the same `backfill:lock:{id}` Redis key the trigger endpoint's
 * 409 check reads. `trigger` mirrors what the original `triggerBackfill`
 * call would have returned, so a caller that missed it (this same tab
 * after a refresh) can resume progress polling with the real
 * `queued_at`/`total_chunks` instead of guessing. */
export type BackfillStatus = {
  source_id: string;
  running: boolean;
  trigger: BackfillTrigger | null;
};

/** Live call to `GET /v1/data-sources/{sourceId}/backfill/status` — the
 * fix for backfill state only ever living in this page's in-memory React
 * state (`operational-tasks/page.tsx`'s `backfillStatus`): call this on
 * mount to find out whether a backfill genuinely already in flight
 * server-side should resume showing as "running" instead of resetting to
 * "Idle" on every page load. No auth required, same reasoning as
 * `triggerBackfill`. */
export async function fetchBackfillStatus(sourceId: string): Promise<BackfillStatus> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/data-sources/${sourceId}/backfill/status`);
  if (!res.ok) {
    throw new Error(`GET /v1/data-sources/${sourceId}/backfill/status failed: ${res.status}`);
  }
  return res.json();
}

/** Live call to `POST /v1/data-sources/{sourceId}/backfill` — real
 * historical fetch for `[start, end]` inclusive (build the pair with
 * `monthToRange` for a whole-month backfill). No auth required, same
 * as `triggerIngestionRun` (see this file's module docstring). 90-day
 * range cap and "already running" 409 are enforced server-side, not
 * duplicated here. */
export async function triggerBackfill(
  sourceId: string,
  start: string,
  end: string,
): Promise<BackfillTrigger> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/data-sources/${sourceId}/backfill`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": crypto.randomUUID(),
    },
    body: JSON.stringify({ start, end, chunk: "P1D", deduplicate: true }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message: string =
      body?.error?.message ?? `POST /v1/data-sources/${sourceId}/backfill failed: ${res.status}`;
    throw new TriggerIngestionError(message, res.status, body?.error?.code ?? null);
  }
  return res.json();
}

// ────────────────────────────────────────────────────────────────────
// Manually rebuilding the warehouse — POST /v1/ingestion/dbt-warehouse/build
// ────────────────────────────────────────────────────────────────────

/** Shape of data-pipeline's `DbtRunResponse`. Unlike `RunTrigger`/
 * `BackfillTrigger`, this isn't a 202-queued shape — `dbt build` runs
 * synchronously within the request (offloaded via `asyncio.to_thread` so
 * it doesn't block the server's event loop, but the HTTP call itself
 * waits for the real exit code), since a build here typically finishes
 * in well under a minute. Give the trigger button its own busy state for
 * that duration, not `BackfillProgress`'s polling shape. */
export type DbtBuildTrigger = {
  subcommand: string;
  target: string;
  exit_code: number;
};

/** Live call to `POST /v1/ingestion/dbt-warehouse/build` — the manual
 * escape hatch for TODO.md's backfill-section gap (a dashboard-triggered
 * backfill lands raw rows but never refreshes `raw_marts.*` on its own).
 * No auth required — deliberately open, same reasoning as
 * `triggerIngestionRun`/`triggerBackfill` (see this endpoint's own
 * comment in `pipelines/routes.py`). Distinct from the general-purpose,
 * admin-gated `/v1/dbt/{subcommand}` — this is a fixed, no-args `build`
 * only.
 *
 * A 409 means another build (from a concurrent manual trigger or a
 * backfill's auto-rebuild) is already running — surfaced via
 * `TriggerIngestionError.code === "dbt_build_in_progress"`, not silently
 * retried; the caller decides whether to tell the operator to wait. */
export async function triggerDbtBuild(): Promise<DbtBuildTrigger> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/ingestion/dbt-warehouse/build`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message: string =
      body?.error?.message ?? `POST /v1/ingestion/dbt-warehouse/build failed: ${res.status}`;
    throw new TriggerIngestionError(message, res.status, body?.error?.code ?? null);
  }
  return res.json();
}

// ────────────────────────────────────────────────────────────────────
// Manually triggering training — POST /v1/model/train
// ────────────────────────────────────────────────────────────────────

/** Shape of data-pipeline's `TrainTriggerResponse`. Unlike `RunTrigger`/
 * `BackfillTrigger`, there's no id to poll here -- the actual work runs
 * in a separate, independently-running consumer process (`train-worker`)
 * this trigger call never talks to directly. Poll forecast-api's
 * `GET /v1/model/versions` for a new version to appear instead (see
 * `fetchModelVersions()` in `lib/emissions.ts`). */
export type TrainTrigger = {
  status: "queued";
  queued_at: string;
  regions: string[];
  window_since: string;
  window_until: string;
  anomalies_flagged: number;
  triggered_by: string;
};

/** Live call to `POST /v1/model/train` (data-pipeline) -- publishes the
 * same training-trigger event the automatic (dbt-build-triggered) path
 * fires, just on demand. No auth required, same reasoning as
 * `triggerIngestionRun`/`triggerBackfill`. No "already in progress"
 * guard server-side -- multiple manual triggers just queue multiple
 * fine-tune events, harmless not conflicting (see that endpoint's own
 * docstring), so this doesn't need one either. */
export async function triggerTraining(opts?: {
  regions?: string[];
  windowHours?: number;
}): Promise<TrainTrigger> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/model/train`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      regions: opts?.regions ?? null,
      window_hours: opts?.windowHours ?? null,
    }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message: string =
      body?.error?.message ?? `POST /v1/model/train failed: ${res.status}`;
    throw new TriggerIngestionError(message, res.status, body?.error?.code ?? null);
  }
  return res.json();
}

/** Shape of data-pipeline's `TrainingRunOut` (`GET /v1/model/training-runs`)
 * -- one `meta._training_log` row. `status === "running"` is the real
 * "is a training run in flight right now" signal (Model Operations
 * TODO.md Phase 4) -- nothing logged this anywhere before that table
 * existed, so `getActiveTasks()`'s `model_training` rows were always
 * fully fictional. */
export type TrainingRunLog = {
  id: string;
  model_name: string;
  status: "running" | "success" | "failed";
  triggered_by: string;
  regions: string[];
  window_start: string;
  window_end: string;
  started_at: string;
  finished_at: string | null;
  run_id: string | null;
  model_version: string | null;
  error_message: string | null;
};

export type TrainingRunsList = {
  data: TrainingRunLog[];
};

export async function fetchTrainingRuns(limit = 20): Promise<TrainingRunsList> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/model/training-runs?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`GET /v1/model/training-runs failed: ${res.status}`);
  }
  return res.json();
}

const TERMINAL_RUN_STATUSES: RunStatus[] = ["success", "failed", "sync_failed", "partial"];

/** Polls `fetchPublicRuns(1, sourceId)` every `intervalMs` for the most
 * recent run of a source, until it reaches a terminal status or
 * `timeoutMs` elapses. There's no run-by-id lookup on the public
 * mirror (and the trigger response's `run_id` is a synthetic id, not
 * the real run's), so this matches by "most recent run for this
 * source" instead — correct in practice because a source only ever
 * has one run in flight at a time (a second trigger while one's
 * already running/staged 409s server-side). Returns a cancel function;
 * callers must call it on unmount so a stale poll doesn't call
 * `onUpdate` after the component's gone. */
export function pollLatestRun(
  sourceId: string,
  onUpdate: (run: PublicRun | null) => void,
  intervalMs = 2000,
  timeoutMs = 30_000,
): () => void {
  let cancelled = false;
  const deadline = Date.now() + timeoutMs;
  const tick = async () => {
    try {
      const res = await fetchPublicRuns(1, sourceId);
      if (cancelled) return;
      const run = res.data[0] ?? null;
      onUpdate(run);
      const terminal = run != null && TERMINAL_RUN_STATUSES.includes(run.status);
      if (!terminal && Date.now() < deadline) {
        setTimeout(tick, intervalMs);
      }
    } catch {
      // A transient poll failure isn't fatal — just stop polling silently
      // rather than flipping the UI to an error state over one dropped
      // request; the next manual trigger will start a fresh poll anyway.
    }
  };
  void tick();
  return () => {
    cancelled = true;
  };
}

/** Verified against a real triggered backfill (30-day range): each day
 * lands as its own `meta._ingest_log` row, `trigger='backfill'`,
 * roughly 5s apart — a live `success`/`failed`/`sync_failed` count per
 * day, not a single run's lifecycle. */
export type BackfillProgress = {
  total: number;
  succeeded: number;
  failed: number;
  done: number; // succeeded + failed -- terminal days observed so far
};

const BACKFILL_FAILED_STATUSES: RunStatus[] = ["failed", "sync_failed"];
const BACKFILL_SUCCEEDED_STATUSES: RunStatus[] = ["success", "partial"];

/** Aggregates the real per-day rows a backfill has produced so far into
 * a day-count summary. A backfill is dozens of independent day-runs
 * (`pipeline.backfill.backfill_day` — one real `meta._ingest_log` row
 * each, confirmed against a live 30-day trigger where AEMO NEM/WEM each
 * landed ~30 rows over a few minutes, roughly 5s apart), so a single
 * "latest run" status chip either freezes on whichever day happened to
 * finish last (misleadingly looking "done" while dozens more are still
 * in flight) or flickers through every status in rapid succession — and
 * misses that some days can genuinely fail while others succeed.
 *
 * Fetches the most recent runs for the source, keeps only the ones at
 * or after `sinceIso` with `trigger === "backfill"` (excludes older
 * "Run now"/schedule runs sharing the same source_id), and tallies them
 * against `BackfillTrigger.total_chunks` (one chunk = one day, always —
 * see that type's own docstring). Keeps polling every `intervalMs`
 * until `timeoutMs` elapses, full stop — callers should size
 * `timeoutMs` off `BackfillTrigger.estimated_duration_seconds` plus a
 * buffer. Same cancel-function contract as `pollLatestRun`. */
export function pollBackfillSummary(
  sourceId: string,
  sinceIso: string,
  totalChunks: number,
  onUpdate: (progress: BackfillProgress) => void,
  intervalMs = 3000,
  timeoutMs = 60_000,
): () => void {
  let cancelled = false;
  const deadline = Date.now() + timeoutMs;
  const since = new Date(sinceIso).getTime();
  const limit = Math.min(500, Math.max(totalChunks * 2, 50));

  const tick = async () => {
    try {
      const res = await fetchPublicRuns(limit, sourceId);
      if (cancelled) return;
      const backfillRuns = res.data.filter(
        (r) => r.trigger === "backfill" && new Date(r.started_at).getTime() >= since,
      );
      const succeeded = backfillRuns.filter((r) => BACKFILL_SUCCEEDED_STATUSES.includes(r.status)).length;
      const failed = backfillRuns.filter((r) => BACKFILL_FAILED_STATUSES.includes(r.status)).length;
      onUpdate({ total: totalChunks, succeeded, failed, done: succeeded + failed });
    } catch {
      // A transient poll failure isn't fatal -- just retry next tick
      // rather than freezing the displayed progress.
    }
    if (!cancelled && Date.now() < deadline) {
      setTimeout(tick, intervalMs);
    }
  };
  void tick();
  return () => {
    cancelled = true;
  };
}

// ────────────────────────────────────────────────────────────────────
// Failed jobs — GET /v1/ingestion/public/failed
// ────────────────────────────────────────────────────────────────────

/** Shape of data-pipeline's `FailedRunOut`. `error.message` is redacted
 * server-side on the public route (`_redact_public_error_message` —
 * strips anything that looks like a secret/credential out of the raw
 * exception text), not something this client does. */
export type FailedRun = {
  run_id: string;
  pipeline_id: string;
  source_id: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  duration_ms: number | null;
  error: { code: string | null; message: string; http_status: number | null; retryable: boolean };
  retry_count: number;
  next_retry_at: string | null;
  in_dlq: boolean;
  can_retry_now: boolean;
};

export type FailedRunsList = {
  meta: { total_failed_24h: number; total_failed_7d: number; as_of: string };
  data: FailedRun[];
  next_cursor: string | null;
  has_more: boolean;
};

export async function fetchPublicFailedRuns(limit = 50): Promise<FailedRunsList> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/ingestion/public/failed?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`GET /v1/ingestion/public/failed failed: ${res.status}`);
  }
  return res.json();
}

// ────────────────────────────────────────────────────────────────────
// Retry queue — GET /v1/ingestion/public/retry-queue
// ────────────────────────────────────────────────────────────────────

/** Shape of data-pipeline's `RetryQueueItem`. Backed by `status='sync_failed'`
 * rows (fetched fine, but the warehouse-sync consumer failed to load
 * them into Postgres) -- `backoff_strategy` is always `"manual"`, there
 * is no automated retry scheduler anywhere in this codebase
 * (`RetryQueueItem`'s own docstring, data-pipeline). */
export type RetryQueueItem = {
  queue_id: string;
  run_id: string;
  pipeline_id: string;
  source_id: string;
  queued_at: string;
  next_retry_at: string | null;
  retry_count: number;
  max_retries: number | null;
  last_error: { code: string | null; message: string; http_status: number | null; retryable: boolean };
  backoff_strategy: "manual";
  backoff_base_seconds: number | null;
};

export type RetryQueueList = {
  meta: { queue_size: number; oldest_queued_at: string | null; as_of: string };
  data: RetryQueueItem[];
};

export async function fetchPublicRetryQueue(limit = 50): Promise<RetryQueueList> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/ingestion/public/retry-queue?limit=${limit}`);
  if (!res.ok) {
    throw new Error(`GET /v1/ingestion/public/retry-queue failed: ${res.status}`);
  }
  return res.json();
}

// ────────────────────────────────────────────────────────────────────
// Scheduler status — GET /v1/ingestion/public/scheduler
// ────────────────────────────────────────────────────────────────────

/** Shape of data-pipeline's `SchedulerResponse`. `active_workers`/
 * `total_workers` are always `1`/`1` -- runs execute in-process
 * (FastAPI `BackgroundTasks` for API-triggered runs, the calling
 * GitHub Actions runner itself for cron-triggered ones), there's no
 * separate worker pool. `prefect_version`/`prefect_api_url` are always
 * `null` -- the `prefect` container in the root `docker-compose.yml` is
 * for the (unbuilt) Forecasting pipeline, not ingestion.
 * (`SchedulerStatus`'s own docstring, data-pipeline.) */
export type SchedulerStatusInfo = {
  status: "healthy";
  as_of: string;
  active_workers: number;
  total_workers: number;
  queue_depth: number;
  prefect_version: string | null;
  prefect_api_url: string | null;
};

export type UpcomingRun = {
  pipeline_id: string;
  source_id: string | null;
  scheduled_at: string;
  trigger: "schedule";
};

export type RecentRunSummary = {
  run_id: string;
  pipeline_id: string;
  status: RunStatus;
  finished_at: string | null;
  duration_ms: number | null;
};

export type SchedulerInfo = {
  scheduler: SchedulerStatusInfo;
  upcoming_runs: UpcomingRun[];
  recent_runs: RecentRunSummary[];
};

export async function fetchPublicScheduler(): Promise<SchedulerInfo> {
  const res = await fetch(`${DATA_PIPELINE_API_URL}/ingestion/public/scheduler`);
  if (!res.ok) {
    throw new Error(`GET /v1/ingestion/public/scheduler failed: ${res.status}`);
  }
  return res.json();
}
