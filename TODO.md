# API:

## Data-Pipeline Service

1	[x] /v1/data-sources	GET	List all  data sources (with health, cron, enabled)
2	[x] /v1/data-sources/{id}	GET / PATCH	Get one / edit cron, cadence, enable/disable
3	[x]/v1/data-sources/{id}/run	POST	Trigger an immediate fetch for this source
4	[x]/v1/data-sources/{id}/backfill	POST	Backfill a date range for this source
5	[x]/v1/data-sources/{id}/health	GET	Health metrics for one source (success rate, p95 latency)
6 /v1/data-sources/{id}/history	GET	Fetch history (last 100 runs for this source)
7	/v1/ingestion/pipelines	GET	List all 8 ingestion pipelines (with status)
8	/v1/ingestion/runs	GET	List recent ingest runs (filter by pipeline, status)
9	/v1/ingestion/runs/{id}	GET	Get one run (with duration, records, errors)
10	/v1/ingestion/failed	GET	List failed jobs
11	/v1/ingestion/retry-queue	GET	List items in retry queue
12	/v1/ingestion/scheduler	GET	Scheduler status (next runs, last runs)
13	/v1/ingestion/{id}/pause	POST	Pause a pipeline
14	/v1/ingestion/{id}/resume	POST	Resume a paused pipeline
15	/v1/data-quality/summary	GET	Overall DQ summary
16	/v1/data-quality/issues	GET	List open DQ issues
17	/v1/data-quality/outliers	GET	List statistical outliers (z-score > 3)
18	/v1/data-quality/schema	GET	Schema drift report
19	/v1/data-quality/recheck/{source}	POST	Re-run DQ tests for one source

POST	Main GHG calculator (Scope 1+2+3)
21	/v1/emissions/factors	GET	List 14 emission factors
22	/v1/emissions/by-source	GET	Emissions aggregated by source
23	/v1/emissions/by-scope	GET	Emissions aggregated by GHG scope
24	/v1/emissions/intensity	GET	Current carbon intensity (gCO₂e/kWh)
25	/v1/emissions/trend	GET	Emissions trend (time series)
26	/v1/emissions/methodology	GET	Methodology content
27	/v1/emissions/intensity-over-time	POST	Compute intensity for a custom period
28	/v1/forecast/{region}	GET	Latest forecast for a region
29	/v1/forecast/latest	GET	Latest forecast across all regions
30	/v1/forecast/accuracy	GET	Forecast accuracy metrics
31	/v1/analytics/executive-kpis	GET	6 KPIs for Executive Dashboard
32	/v1/analytics/emissions-by-source	GET	Emissions by source
33	/v1/analytics/emissions-trend	GET	Emissions trend (with P10/P90 band)
34	/v1/analytics/emissions-trend/daily	GET	Daily emissions trend
35	/v1/analytics/forecast-preview	GET	Next 4h forecast preview
36	/v1/analytics/emissions-snapshot	GET	Last 24h emissions snapshot
37	/v1/analytics/operations	GET	Operations Dashboard summary
38	/v1/analytics/scope	GET	Energy Analytics → Scope breakdown
39	/v1/analytics/industry	GET	Energy Analytics → industry comparison
40	/v1/analytics/regional	GET	Energy Analytics → regional comparison
41	/v1/analytics/intensity	GET	Energy Analytics → intensity over time
42	/v1/analytics/cost-vs-emissions	GET	Energy Analytics → cost vs emissions
43	/v1/analytics/opportunities	GET	Energy Analytics → reduction opportunities
44	/v1/reports/fire-schedule/{schedule_id}	POST	Trigger a scheduled report
45	/v1/reports/library	GET	List all reports
46	/v1/models	GET	List all models in MLflow
47	/v1/models/{id}	GET	Get one model (with all versions)
48	/v1/models/{id}/promote	POST	Promote a model version to production
49	/v1/models/{id}/archive	POST	Archive a model version
50	/v1/models/{id}/metrics	GET	Metrics for a model version
51	/v1/training/experiments	GET	List MLflow experiments
52	/v1/training/runs	GET / POST	List / trigger a training run
53	/v1/training/runs/{id}/logs	GET	Get logs for a training run
54	/v1/operational-tasks	GET	List operational tasks
55	/v1/operational-tasks/queue	GET	List pending tasks
56	/v1/operational-tasks/history	GET	List completed/rejected tasks
57	/v1/operational-tasks/{id}/approve	POST	Approve a task
58	/v1/operational-tasks/{id}/reject	POST	Reject a task
59	/v1/system-health/summary	GET	Overall system health
60	/v1/system-health/services	GET	Per-service health
61	/v1/system-health/disk	GET	Disk usage per volume
62	/v1/system-health/uptime	GET	Uptime per service
63	/v1/system-health/errors	GET	Recent errors (last 24h)
64	/v1/system-health/restart/{service}	POST	Restart a service (admin only)
65	/v1/anomalies	GET	List anomalies
66	/v1/anomalies/{id}	GET	Get one anomaly (with explanation)
67	/v1/anomalies/{id}/acknowledge	POST	Acknowledge an anomaly
68	/v1/anomalies/{id}/resolve	POST	Resolve an anomaly
69	/v1/anomalies/rules	GET / PATCH	List / update anomaly rules
70	/v1/warehouse/tables	GET	List all warehouse tables
71	/v1/warehouse/tables/{name}/schema	GET	Get schema for one table
72	/v1/warehouse/query	POST	Read-only SQL query (row limit + safety)
73	/v1/warehouse/runs	GET	List dbt run history
74	/v1/warehouse/run	POST	Trigger a dbt run (async)
75	/healthz + /readyz	GET	Liveness + readiness probes
76	/metrics + /version	GET	Prometheus + service version

  ## IAM service
#	Endpoint	Method	Purpose
1	/v1/auth/signup	POST	Create account + send verify-email
2	/v1/auth/verify-email	POST	Confirm email with token from email
3	/v1/auth/login	POST	Email + password → JWT pair
4	/v1/auth/refresh	POST	Rotate access token using refresh
5	/v1/auth/logout	POST	Revoke current refresh token
6	/v1/auth/logout-all	POST	Revoke all sessions for user
7	/v1/auth/forgot-password	POST	Send reset email
8	/v1/auth/reset-password	POST	Set new password with token
9	/v1/auth/me	GET	Current user + attributes
10	/v1/auth/mfa/{setup,verify,disable}	POST	TOTP enrollment / verify / disable (3 actions)
11	/v1/users	GET / POST	List / create users
12	/v1/users/{id}	GET / PATCH / DELETE	Manage one user
13	/v1/users/{id}/attributes	GET / PATCH	Get / set custom attributes
14	/v1/users/{id}/disable	POST	Disable a user (keep data, block login)
15	/v1/users/{id}/enable	POST	Re-enable a disabled user
16	/v1/orgs	GET / POST	List / create orgs (super-admin)
17	/v1/orgs/{id}	GET / PATCH / DELETE	Manage one org
18	/v1/orgs/{id}/members	GET / POST	List / add members
19	/v1/orgs/{id}/members/{user_id}	DELETE	Remove a member
20	/v1/attributes/schemas	GET / POST	List / create attribute schemas
21	/v1/attributes/schemas/{name}	GET / PATCH / DELETE	Manage one schema
22	/v1/policies	GET / POST	List / create policies
23	/v1/policies/{id}	GET / PATCH / DELETE	Manage one policy
24	/v1/policies/{id}/test	POST	Test a policy against sample request
25	/v1/policies/import	POST	Bulk import policies from JSON / YAML
26	/v1/authorize	POST	ABAC decision engine (core, called by every other service)
27	/v1/audit	GET	List audit entries (with filters)
28	/v1/audit/{id}	GET	Get one audit entry (full request/response snapshot)
29	/v1/audit/export	GET	Export audit log as CSV / JSON
30	/v1/sessions	GET / DELETE	List my active sessions / revoke all (except current)
31	/v1/sessions/{id}	DELETE	Revoke a specific session
32	/v1/tokens/introspect	POST	Check if a token is valid (RFC 7662)
33	/v1/tokens/revoke	POST	Revoke a token by jti
34	/healthz	GET	Liveness probe
35	/readyz	GET	Readiness probe
36	/metrics + /version	GET	Prometheus + service version


## 1.7 Notification service — full endpoint list

| # | Endpoint | Method | Purpose |
|---|---|---|---|
| 1 | `/v1/notify/email` | POST | Send one email |
| 2 | `/v1/notify/webhook` | POST | Send one webhook |
| 3 | `/v1/notify/batch` | POST | Send up to 100 mixed notifications |
| 4 | `/v1/notify` | GET | List with filters |
| 5 | `/v1/notify/{id}` | GET | Get one with full delivery history |
| 6 | `/v1/notify/{id}/retry` | POST | Re-queue failed/DLQ |
| 7 | `/v1/notify/{id}` | DELETE | Cancel/delete |
| 8 | `/v1/notify/dlq` | GET | List DLQ |
| 9 | `/v1/notify/dlq/replay-all` | POST | Replay all DLQ |
| 10 | `/v1/notify/stats` | GET | Delivery stats |
| 11 | `/v1/notify/templates` | GET / POST | List / create |
| 12 | `/v1/notify/templates/{id}` | GET / PATCH / DELETE | Manage one |
| 13 | `/v1/notify/templates/{id}/preview` | POST | Render preview |
| 14 | `/healthz` | GET | Liveness |
| 15 | `/readyz` | GET | Readiness |
| 16 | `/metrics` + `/version` | GET | Ops |


## 2.9 Reporting service — full endpoint list 

| # | Endpoint | Method | Purpose |
|---|---|---|---|
| 1 | `/v1/reports/generate` | POST | Queue a new report |
| 2 | `/v1/reports` | GET | List with filters + pagination |
| 3 | `/v1/reports/{id}` | GET | Get metadata |
| 4 | `/v1/reports/{id}` | DELETE | Delete + remove file |
| 5 | `/v1/reports/{id}/duplicate` | POST | Copy a report |
| 6 | `/v1/reports/{id}/preview` | POST | Generate low-res preview |
| 7 | `/v1/reports/{id}/download-url` | POST | Get signed URL (5 min TTL) |
| 8 | `/v1/reports/{id}/download` | GET | Stream file via X-Accel-Redirect |
| 9 | `/v1/reports/schedules` | GET / POST | List / create |
| 10 | `/v1/reports/schedules/{id}` | GET / PATCH / DELETE | Manage one |
| 11 | `/v1/reports/schedules/{id}/run-now` | POST | Trigger immediate run |
| 12 | `/v1/reports/schedules/{id}/history` | GET | Reports from this schedule |
| 13 | `/v1/reports/templates` | GET / POST | List / create |
| 14 | `/v1/reports/templates/{id}` | GET / PATCH / DELETE | Manage one |
| 15 | `/v1/reports/templates/{id}/preview` | POST | Render preview |
| 16 | `/v1/reports/jobs` | GET | List render jobs |
| 17 | `/v1/reports/jobs/{id}` | GET | One job with progress log |
| 18 | `/v1/reports/jobs/{id}/cancel` | POST | Cancel running job |
| 19 | `/v1/reports/stats` | GET | Stats |
| 20 | `/healthz` | GET | Liveness |
| 21 | `/readyz` | GET | Readiness |
| 22 | `/metrics` | GET | Prometheus |
| 23 | `/version` | GET | Version info |
