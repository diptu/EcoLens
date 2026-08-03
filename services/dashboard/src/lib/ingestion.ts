/**
 * data-pipeline client — ingestion domain.
 *
 * Talks to `ecolens.ingestion.api.routes` (mounted on data-pipeline's
 * control API, `ecolens/api/app.py`, port 8001) via
 * `DATA_PIPELINE_CONTROL_API_URL` — the *real*, already-implemented
 * routes (`/ingestion/historical`, `/ingestion/daily-counts`,
 * `/ingestion/retry-missing`), not the `/v1/data-sources/*` +
 * `/v1/ingestion/public/*` contract an earlier version of this file
 * called: that contract is still just planned (TODO.md rows 1-14) —
 * grepping the whole data-pipeline service turns up no matching routes,
 * and no IAM↔data-pipeline JWT bridge either, so those calls always
 * 404ed. This version only exposes what data-pipeline can actually do
 * today: trigger a backfill in the background and poll it by job id,
 * same shape as `forecasting.api`'s own job-polling endpoints.
 *
 * These routes currently have no auth dependency on the data-pipeline
 * side (see `ecolens/ingestion/api/routes.py`) — CORS is open to the
 * dashboard's dev origin (`Settings.api_cors_origins`), so a plain
 * `fetch()` from the browser works, but so would anyone else's; that's
 * a data-pipeline-side gap to close later, not something this client
 * can paper over.
 */

import { DATA_PIPELINE_CONTROL_API_URL } from "./env";

export type Source = "bom" | "aemo_nem" | "aemo_wem" | "openelectricity" | "holidays";

/** The 5 real ingestion sources plus the dbt-warehouse transform step —
 * replaces the old fictional 8-pipeline mock (`lib/dashboards.ts`'s
 * `getPipelines()`, which invented sources like "ENTSO-E API"/"EIA API"
 * that don't exist anywhere in this platform). The warehouse build has
 * no matching route here (it isn't an ingestion fetch); listed with
 * `triggerable: false` so the UI can show it without wiring a button
 * that would always fail. */
export type PipelineCatalogEntry = {
  id: Source | "dbt-warehouse";
  label: string;
  triggerable: boolean;
};

export const PIPELINE_CATALOG: PipelineCatalogEntry[] = [
  { id: "aemo_nem", label: "AEMO NEM Ingest", triggerable: true },
  { id: "aemo_wem", label: "AEMO WEM Ingest", triggerable: true },
  { id: "bom", label: "Bureau of Meteorology Ingest", triggerable: true },
  { id: "openelectricity", label: "OpenElectricity Ingest", triggerable: true },
  { id: "holidays", label: "AEMO Public Holidays Ingest", triggerable: true },
  { id: "dbt-warehouse", label: "dbt Warehouse Build", triggerable: false },
];

export class IngestionApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "IngestionApiError";
  }
}

async function parseOrThrow<T>(res: Response, label: string): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const message: string = body?.detail ? String(body.detail) : `${label} failed: ${res.status}`;
    throw new IngestionApiError(message, res.status);
  }
  return res.json();
}

/** Either a single `date`, or a `startDate`+`endDate` range — mirrors
 * `_resolve_date_range`'s xor validation on the backend (sending both
 * or neither gets you its 422, not a client-side guess here). */
export type DateSelector = { date: string } | { startDate: string; endDate: string };

function dateParams(selector: DateSelector): Record<string, string> {
  return "date" in selector
    ? { date: selector.date }
    : { start_date: selector.startDate, end_date: selector.endDate };
}

export type JobStatus = "running" | "completed" | "failed";

export type IngestJob = {
  job_id: string;
  status: JobStatus;
  started_at: string;
  finished_at: string | null;
  written: number | null;
  error: string | null;
  [key: string]: unknown;
};

export type TriggerResponse = {
  status: "started";
  job_id: string;
  source: Source;
  start_date: string;
  end_date: string;
};

/** `POST /ingestion/historical` — backfills one source in the
 * background; returns immediately with a `job_id` to poll. */
export async function triggerHistoricalIngest(
  source: Source,
  selector: DateSelector,
): Promise<TriggerResponse> {
  const params = new URLSearchParams({ source, ...dateParams(selector) });
  const res = await fetch(`${DATA_PIPELINE_CONTROL_API_URL}/ingestion/historical?${params}`, {
    method: "POST",
  });
  return parseOrThrow<TriggerResponse>(res, "POST /ingestion/historical");
}

/** `GET /ingestion/historical/{job_id}` — poll a triggered backfill. */
export async function getHistoricalIngestJob(jobId: string): Promise<IngestJob> {
  const res = await fetch(`${DATA_PIPELINE_CONTROL_API_URL}/ingestion/historical/${jobId}`);
  return parseOrThrow<IngestJob>(res, `GET /ingestion/historical/${jobId}`);
}

export type DailyCounts = {
  source: Source;
  start_date: string;
  end_date: string;
  counts: { date: string; count: number }[];
};

/** `GET /ingestion/daily-counts` — synchronous row-count-per-day check,
 * used to find gaps before deciding whether to retry. */
export async function fetchDailyCounts(
  source: Source,
  selector: DateSelector,
): Promise<DailyCounts> {
  const params = new URLSearchParams({ source, ...dateParams(selector) });
  const res = await fetch(`${DATA_PIPELINE_CONTROL_API_URL}/ingestion/daily-counts?${params}`);
  return parseOrThrow<DailyCounts>(res, "GET /ingestion/daily-counts");
}

export type RetryMissingResponse =
  | { status: "no_gaps_found"; source: Source; days_checked: number; missing_dates: [] }
  | {
      status: "started";
      job_id: string;
      source: Source;
      days_checked: number;
      missing_dates: string[];
    };

/** `POST /ingestion/retry-missing` — finds zero-row (or, with
 * `minExpectedCount`, short) days in range and re-ingests just those. */
export async function triggerRetryMissing(
  source: Source,
  selector: DateSelector,
  minExpectedCount?: number,
): Promise<RetryMissingResponse> {
  const params = new URLSearchParams({ source, ...dateParams(selector) });
  if (minExpectedCount != null) params.set("min_expected_count", String(minExpectedCount));
  const res = await fetch(`${DATA_PIPELINE_CONTROL_API_URL}/ingestion/retry-missing?${params}`, {
    method: "POST",
  });
  return parseOrThrow<RetryMissingResponse>(res, "POST /ingestion/retry-missing");
}

/** `GET /ingestion/retry-missing/{job_id}` — poll a triggered retry. */
export async function getRetryMissingJob(jobId: string): Promise<IngestJob> {
  const res = await fetch(`${DATA_PIPELINE_CONTROL_API_URL}/ingestion/retry-missing/${jobId}`);
  return parseOrThrow<IngestJob>(res, `GET /ingestion/retry-missing/${jobId}`);
}

/** Polls a job endpoint every `intervalMs` until it leaves `"running"`.
 * Shared by both `/ingestion/historical` and `/ingestion/retry-missing`
 * jobs — same `{status, written, error}` shape on both. Returns a
 * cancel function; callers must call it on unmount so a stale poll
 * doesn't call `onUpdate` after the component's gone. */
export function pollIngestJob(
  fetchJob: (jobId: string) => Promise<IngestJob>,
  jobId: string,
  onUpdate: (job: IngestJob) => void,
  intervalMs = 1500,
): () => void {
  let cancelled = false;
  const tick = async () => {
    try {
      const job = await fetchJob(jobId);
      if (cancelled) return;
      onUpdate(job);
      if (job.status === "running") {
        setTimeout(tick, intervalMs);
      }
    } catch (err) {
      if (cancelled) return;
      onUpdate({
        job_id: jobId,
        status: "failed",
        started_at: "",
        finished_at: null,
        written: null,
        error: err instanceof Error ? err.message : "poll failed",
      });
    }
  };
  void tick();
  return () => {
    cancelled = true;
  };
}
