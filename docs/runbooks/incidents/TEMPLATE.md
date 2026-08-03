# Incident: <one-line summary>

Filed under `docs/runbooks/incidents/YYYY-MM-DD.md` (the date the incident
*started*, not when this file was written). If more than one incident
happens on the same day, suffix a slug: `2026-07-19-bom-circuit-open.md`.

- **Date / time detected:** <UTC timestamp>
- **Date / time resolved:** <UTC timestamp, or "ongoing">
- **Sources affected:** <e.g. `bom`, `aemo-nem`, all>
- **Severity:** <e.g. one source late vs. all ingestion down>

## What broke

<Root cause — the actual failure, not just the symptom. Reference the
"Failure Modes & Recovery" table in
`pipeline/tasks/task.md` if this matches one of the 6 known modes; note
if it's a new one.>

## How long was it down

<Wall-clock duration from `meta._ingest_log`'s first `status='failed'`
row to the first `status='success'` row after recovery. Include the
query you ran, e.g.:
`SELECT source, status, started_at, error_message FROM meta._ingest_log WHERE source = '<source>' ORDER BY started_at DESC LIMIT 20;`>

## How much data was lost

<Usually zero — the recovery playbook's step 4 (`scripts/backfill.py`)
replays from the upstream API, and the idempotency guarantees
(`task.md`) mean re-running never double-counts. Note explicitly if
this incident was an exception (e.g. upstream retention window expired
before backfill ran).>

## How it was detected

<Manual check, an alert, a downstream consumer noticing stale data,
etc. If this wasn't caught by monitoring, that's worth calling out — it
becomes a candidate for `task.md`'s "Monitoring you should set up"
checklist.>

## Recovery steps taken

<What you actually ran, in order — doesn't need to match the canonical
"Recovery order of operations" exactly, but note where it deviated and
why.>

```bash
# example
redis-cli DEL ecolens:circuit_breaker:bom
python scripts/backfill.py --source bom --from 2026-07-19 --to 2026-07-19
```

## Follow-ups

<Concrete action items — a TODO.md ticket, a config change, a new
alert. An incident with no follow-up items usually means the root
cause wasn't actually found.>

- [ ] ...
