"use client";

/**
 * React Query provider (ECO-132). One QueryClient per browser session --
 * created lazily inside useState so server-rendered/static-exported pages
 * never share a client across requests (this app is `output: "export"`,
 * so every page is prerendered once at build time; the client only ever
 * exists in the browser after hydration).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";

export function QueryProvider({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // The backend (forecast-api) isn't guaranteed to be running in
            // every environment this static export gets viewed in -- fail
            // fast rather than retrying a dead connection for a while.
            retry: 1,
            staleTime: 30_000,
            refetchOnWindowFocus: false,
          },
        },
      }),
  );

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
