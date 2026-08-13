# Incident postmortems

`pipeline/tasks/task.md`'s recovery playbook ends every incident with:

> **7. POST-MORTEM** — write a note in `docs/runbooks/incidents/YYYY-MM-DD.md`.
> What broke? How long was it down? How much data lost? How long to
> recover? This builds into the operational knowledge over time.

This directory is where those notes live.

## Convention

- One file per incident: `YYYY-MM-DD.md`, dated to when the incident
  *started*. Two incidents on the same day get a slug suffix:
  `2026-07-19-bom-circuit-open.md`, `2026-07-19-s3-outage.md`.
- Copy `TEMPLATE.md` to start a new one — don't write from a blank
  page, the template's sections are the four questions above plus
  enough structure to make incidents comparable to each other over
  time.
- Write it **after** recovery (step 7 comes last in the playbook, once
  the "VERIFY" step has confirmed the system is actually healthy
  again) — not as a running log during the incident.
- Keep it short. This is an operational record, not a full RCA
  document — a page is usually enough.

## Why this exists

A single incident is easy to remember. The value here is the
*pattern* across many: which source fails most often, whether the
same root cause keeps recurring, whether recovery time is trending up
or down. Nobody will notice that pattern without a written record —
this directory is that record.
