/**
 * Browser `localStorage` cache — a second, client-side cache layer for
 * dashboard components that fetch from real, already-cached backend
 * endpoints. This is NOT a replacement for `forecast-api`'s own Redis
 * caching (`GET /v1/forecast` already caches server-side: an L1
 * in-process TTL cache in front of an L2 Redis cache, see
 * `services/forecast-api/app/core/local_cache.py` +
 * `app/api/v1/forecast/routes.py`'s `forecast_local_cache`) — that cache
 * still exists to make a real cache *miss* here cheap. This layer solves
 * a different problem: it survives a full page reload/new tab, so a
 * component can render the last real value immediately on mount instead
 * of a loading skeleton, then quietly refresh from the network — a
 * stale-while-revalidate read, not a replacement for the live fetch.
 *
 * Used by the Executive Dashboard's "Demand Forecast Preview" card
 * (2026-08-11) for exactly this: `fetchDemandForecast`'s response and
 * the real actual-demand window backing that same chart.
 */
"use client";

type CacheEnvelope<T> = { value: T; cachedAt: number };

const PREFIX = "ecolens:cache:";

function safeStorage(): Storage | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage;
  } catch {
    // Private browsing / storage disabled by the browser -- fail closed,
    // every call below just becomes a real no-op cache miss, not a crash.
    return null;
  }
}

/** Real cached value for `key` if present and younger than `maxAgeMs`,
 * else `null`. A stale entry is left in place (not deleted) so a caller
 * can still fall back to it if the live refresh that follows fails --
 * `setCached` overwrites it on the next successful fetch regardless. */
export function getCached<T>(key: string, maxAgeMs: number): T | null {
  const storage = safeStorage();
  if (!storage) return null;
  try {
    const raw = storage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEnvelope<T>;
    if (typeof parsed.cachedAt !== "number" || Date.now() - parsed.cachedAt > maxAgeMs) {
      return null;
    }
    return parsed.value;
  } catch {
    return null;
  }
}

/** `getCached`'s own real age, in ms, regardless of `maxAgeMs` freshness
 * -- callers that render a stale value while refreshing (e.g. "as of
 * 4m ago") need the real number, not just a fresh/stale boolean. */
export function getCachedAgeMs(key: string): number | null {
  const storage = safeStorage();
  if (!storage) return null;
  try {
    const raw = storage.getItem(PREFIX + key);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CacheEnvelope<unknown>;
    if (typeof parsed.cachedAt !== "number") return null;
    return Date.now() - parsed.cachedAt;
  } catch {
    return null;
  }
}

export function setCached<T>(key: string, value: T): void {
  const storage = safeStorage();
  if (!storage) return;
  try {
    const envelope: CacheEnvelope<T> = { value, cachedAt: Date.now() };
    storage.setItem(PREFIX + key, JSON.stringify(envelope));
  } catch {
    // Quota exceeded, or storage became unavailable mid-session -- not
    // fatal, this write is just skipped; the next successful fetch tries
    // again.
  }
}
