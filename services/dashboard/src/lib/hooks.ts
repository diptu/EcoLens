"use client";

/** ECO-130/132: React Query hooks over the forecast-api client. */
import { useQuery } from "@tanstack/react-query";

import { fetchForecast, fetchForecastApiHealth } from "@/lib/api-client";

export function useForecast(region: string, horizon?: number) {
  return useQuery({
    queryKey: ["forecast", region, horizon],
    queryFn: ({ signal }) => fetchForecast(region, horizon, signal),
  });
}

export function useForecastApiHealth() {
  return useQuery({
    queryKey: ["forecast-api-health"],
    queryFn: ({ signal }) => fetchForecastApiHealth(signal),
    // Health is cheap and changes fast (model reload state); don't rely
    // on the default 30s staleTime for it.
    staleTime: 5_000,
  });
}
