# dbt commands: `build`, `run`, `test`

What each of the three dbt subcommands exposed via `POST /v1/dbt/{subcommand}`
(ECO-D22) actually does, both in general and against ecoLens's own dbt DAG.

> **Current state:** the dbt *project itself* (`dbt_project.yml`,
> `models/{staging,intermediate,marts}/`, `seeds/emissions_factors.csv` —
> see README's Repository layout) hasn't been scaffolded in this repo yet,
> and `dbt` isn't installed anywhere in this environment. `ecolens.dbt_runner.runner.run_dbt`
> (ECO-D21) shells out to a `dbt` binary on `PATH`; today that call fails
> immediately with "command not found" (exit code 127), which the API
> surfaces as a `500`. Everything below describes what each command *will*
> do once both of those exist — it's the contract the endpoints are built
> against, not a description of a currently-working pipeline.

## The DAG these commands operate on

Per README's dbt design and `docs/data/ingestion-schema.md`'s raw tables:

```
seeds/emissions_factors.csv
        │
raw.* (populated by ECO-D25-D29 ingestion tasks, landed via migrations 0002-0006)
        │
models/staging/          stg_aemo_nem_dispatch, stg_aemo_wem_dispatch,
                          stg_openelectricity_mix, stg_bom_observations,
                          stg_aemo_holidays
        │
models/intermediate/     int_demand_with_weather, int_mix_share,
                          int_carbon_intensity
        │
models/marts/            fct_energy_demand, fct_emissions_5min,
                          fct_carbon_intensity, dim_energy_mix, dim_facility
        │
schema tests             not-null / unique / relationships / accepted_values
                          on the above, plus the singular "system-level
                          carbon intensity within ±2% of NGER" test
```

Every command below is invoked as:

```
dbt <subcommand> --project-dir <settings.dbt_project_dir> --target <target>
```

(`ecolens.dbt_runner.runner.run_dbt`, ECO-D21 — `project_dir` defaults to
`Settings.dbt_project_dir` = `dbt/ecolens`, `target` defaults to
`Settings.dbt_target` = `prod` unless overridden in the request body).

## `dbt build`

**`POST /v1/dbt/build`**

Runs the *entire* DAG — seeds, models, snapshots, and tests — together, in
dependency order, node by node. If `stg_aemo_nem_dispatch` fails to build,
everything downstream of it (`int_demand_with_weather`,
`fct_energy_demand`, ...) is skipped rather than run against stale or
missing data; siblings that don't depend on the failed node still run.

This is the command the daily/scheduled pipeline run should use (see
`infra/cron/ecolens-crontab`, ECO-D59) — it's the only one of the three
that both freshens the seed data and gates downstream models on upstream
success in one pass.

What actually happens, in order:
1. Loads `seeds/emissions_factors.csv` into the warehouse (equivalent to
   `dbt seed`).
2. Materializes every model in `models/staging/`, `models/intermediate/`,
   `models/marts/` per each model's configured materialization
   (`dbt_project.yml`: `staging` → view, `intermediate` → ephemeral,
   `marts` → table).
3. Runs every test attached to a model immediately after that model
   builds, not all at the end — so a broken staging test blocks its
   downstream marts from ever running.

Exit code is non-zero if *any* node (seed, model, or test) fails; the API
returns `500` in that case (`ecolens/api/routers/dbt.py`).

## `dbt run`

**`POST /v1/dbt/run`**

Materializes models only — staging, intermediate, and marts, in DAG
order. Does **not** run tests, and does **not** reload seeds. If
`emissions_factors.csv` changed since the last `dbt seed`/`dbt build`,
`dbt run` alone won't pick that up.

Useful for a fast rebuild during development (e.g. iterating on
`fct_energy_demand.sql`) when you don't want to pay for the full test
suite on every save, or via `extra_args: ["--select", "fct_energy_demand"]`
to rebuild one model and its ancestors without touching the rest of the
DAG.

## `dbt test`

**`POST /v1/dbt/test`**

Runs tests only, against whatever's *already* materialized in the
warehouse — schema tests (`not_null`, `unique`, `relationships`,
`accepted_values`, defined in each model's `.yml`) and singular tests
(standalone `.sql` files under `tests/`, e.g. the "system-level carbon
intensity within ±2% of the published NGER national value" check from
`Contributing.md`'s "Adding a new emissions factor source" section).

Does not build or rebuild anything — if a model is stale or was never
built, `dbt test` happily tests the old data (or errors that the
relation doesn't exist yet if it was never built at all). This is the
command CI should call after a `dbt run` to fail the build on data-quality
regressions without re-materializing everything twice.

## Summary

| | seeds | models | tests | typical use |
| --- | --- | --- | --- | --- |
| `build` | ✅ | ✅ (DAG-gated) | ✅ (DAG-gated) | scheduled pipeline run |
| `run` | ❌ | ✅ | ❌ | fast local iteration |
| `test` | ❌ | ❌ | ✅ | CI check after a build/run |

All three accept `extra_args` in the request body (e.g.
`{"extra_args": ["--select", "stg_aemo_nem_dispatch+"]}`) which are passed
straight through to the `dbt` CLI — dbt's own `--select`/`--exclude`
syntax works exactly as it would on the command line.
