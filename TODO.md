# TODO's

## Storage
[]store all asstets & art-effects on claudeflare R2

## Performance optimization:

- [] Prefetch Data Before Navigation: prefetch pages in the background. Ensure you are using framework-level prefetching.
-[] Stream inference updates or pipeline progress indicators back to Next.js progressively,


## FastAPI Backend: Payload Compression & Asynchronous Processing

-  []Gzip Compression Middleware: Enable built-in compression in FastAPI to drastically reduce JSON payload size for large time-series arrays.

## Response Caching & Edge Delivery

-[] FastAPI Response Caching: For heavy forecasting endpoints that only update after  5-minute cron/dbt pipeline runs, use fastapi-cache backed by Redis. This prevents FastAPI from recalculating or querying the database repeatedly for identical requests within that 5-minute window.

Cache-Control Headers: Set explicit cache headers (Cache-Control: public, s-maxage=300, stale-while-revalidate=60) on  FastAPI GET endpoints so that Vercel or CDN layers cache static historical carbon analytics closer to your users.