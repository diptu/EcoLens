/**
 * ECO-130: typed client for forecast-api (and, if/when it's needed,
 * warehouse-api). Base URLs come from NEXT_PUBLIC_* env vars so they can
 * differ per environment; see .env.example. Sensible localhost defaults
 * so `pnpm dev` works against a locally-running `make api` without any
 * env setup.
 *
 * Every call site should go through `useForecast`/`useHealth` (see
 * hooks.ts) rather than calling `fetchForecast` directly outside of
 * React Query -- that's what gives callers the loading/error states and
 * automatic retry/caching this app relies on to degrade gracefully when
 * the backend isn't running (which it won't be in most environments
 * this static export gets viewed in).
 */

export const FORECAST_API_BASE =
  process.env.NEXT_PUBLIC_FORECAST_API_BASE ?? "http://localhost:8003";

export const WAREHOUSE_API_BASE =
  process.env.NEXT_PUBLIC_WAREHOUSE_API_BASE ?? "http://localhost:8002";

export type ForecastStep = {
  ts: string;
  horizon_step: number;
  p10: number | null;
  p50: number | null;
  p90: number | null;
};

export type ForecastResponse = {
  region: string;
  generated_at: string;
  as_of: string;
  model: string;
  interval_minutes: number;
  steps: ForecastStep[];
};

export type HealthResponse = {
  status: string;
  pg: Record<string, unknown>;
  cache: Record<string, unknown>;
  model: Record<string, unknown>;
  uptime_seconds: number;
};

class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(url, { signal });
  } catch (err) {
    // Covers "backend not running" (connection refused) -- the common
    // case for anyone viewing this static export without forecast-api up.
    throw new ApiError(
      `Could not reach ${url}. Is the backend running? (${err instanceof Error ? err.message : String(err)})`,
    );
  }
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(`${res.status} ${res.statusText}${body ? `: ${body}` : ""}`, res.status);
  }
  return res.json() as Promise<T>;
}

export function fetchForecast(
  region: string,
  horizon?: number,
  signal?: AbortSignal,
): Promise<ForecastResponse> {
  const url = new URL(`/v1/forecast/${encodeURIComponent(region)}`, FORECAST_API_BASE);
  if (horizon) url.searchParams.set("horizon", String(horizon));
  return fetchJson<ForecastResponse>(url.toString(), signal);
}

export function fetchForecastApiHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return fetchJson<HealthResponse>(new URL("/health", FORECAST_API_BASE).toString(), signal);
}
