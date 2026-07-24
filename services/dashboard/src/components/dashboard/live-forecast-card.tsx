"use client";

/**
 * ECO-130: the one genuinely-live piece of this dashboard -- everything
 * else on this page still reads static/demo data (see root TODO.md).
 * Fetches services/forecast-api's real /v1/forecast/{region} via React
 * Query. Degrades to a clear "backend unavailable" state rather than
 * crashing the page when forecast-api isn't running, which is the
 * common case for anyone viewing this app without the full stack up.
 */
import { useState } from "react";

import { Card } from "@/components/dashboard/card";
import { useForecast } from "@/lib/hooks";

const REGIONS = ["NSW1", "QLD1", "VIC1", "SA1", "TAS1", "WEM"] as const;

export function LiveForecastCard() {
  const [region, setRegion] = useState<(typeof REGIONS)[number]>("NSW1");
  const { data, isLoading, isError, error, dataUpdatedAt } = useForecast(region, 6);

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          Live Demand Forecast
          <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 text-[10px] font-medium text-emerald-300">
            forecast-api
          </span>
        </span>
      }
      subtitle="The only section on this page reading real data, not the static demo dataset."
      actions={
        <select
          value={region}
          onChange={(e) => setRegion(e.target.value as (typeof REGIONS)[number])}
          className="rounded-md border border-white/10 bg-white/5 px-2 py-1 text-xs text-white/70"
        >
          {REGIONS.map((r) => (
            <option key={r} value={r} className="bg-[#0a1410]">
              {r}
            </option>
          ))}
        </select>
      }
    >
      {isLoading && <p className="text-xs text-white/50">Loading forecast…</p>}

      {isError && (
        <div className="rounded-md border border-amber-400/30 bg-amber-400/10 p-3 text-xs text-amber-200">
          <p className="font-medium">forecast-api unavailable</p>
          <p className="mt-1 text-amber-200/80">
            {error instanceof Error ? error.message : "Unknown error"}
          </p>
          <p className="mt-1 text-amber-200/60">
            Start it with <code className="rounded bg-black/30 px-1">make api</code> to see live data here.
          </p>
        </div>
      )}

      {data && (
        <div>
          <div className="mb-2 flex items-center justify-between text-[10px] text-white/40">
            <span>
              model: <span className="text-white/70">{data.model}</span>
            </span>
            <span>as of {new Date(data.as_of).toLocaleString()}</span>
          </div>
          <div className="grid grid-cols-3 gap-2 text-center text-xs sm:grid-cols-6">
            {data.steps.map((s) => (
              <div key={s.horizon_step} className="rounded-md border border-white/5 bg-white/[0.02] p-2">
                <p className="text-white/40">{new Date(s.ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</p>
                <p className="mt-1 font-semibold text-white">{s.p50 !== null ? Math.round(s.p50).toLocaleString() : "—"}</p>
                <p className="text-[10px] text-white/40">
                  {s.p10 !== null && s.p90 !== null
                    ? `${Math.round(s.p10).toLocaleString()}–${Math.round(s.p90).toLocaleString()}`
                    : "no data yet"}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-2 text-[10px] text-white/30">Last fetched {new Date(dataUpdatedAt).toLocaleTimeString()}</p>
        </div>
      )}
    </Card>
  );
}
