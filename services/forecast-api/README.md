# forecast-api

Serves the demand-forecast model `data-pipeline` trains and registers in
MLflow, plus derived emissions/footprint reads from the Postgres warehouse
`data-pipeline`'s dbt project builds. Never trains — only loads. See the
repo root [`README.md`](../../README.md)'s "ML pipeline" and
"Microservices" sections for the full picture, and `TODO.md`'s Forecasting
section for current scope/known gaps.

```
uv run --directory services/forecast-api uvicorn app.main:app --reload --port 8000
```
