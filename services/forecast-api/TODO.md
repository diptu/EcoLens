# Forecast API Roadmap & Technical Debt

## 🚦 Status Legend
- `[ ]` Backlog: Not started
- `[/]` In Progress: Actively being addressed
- `[!]` Blocker: Prevents production stability/scaling
- `[✓]` Completed

---

## 🏗 Architectural Debt
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-F01]** | P2 | TBD | Transition from Uvicorn to Uvicorn+ Gunicorn . |


## ⚡ Performance & Scalability
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-P01]** | P1 | TBD | Implement Redis caching layer for `/forecast/latest`. |
| `[ ]` | **[ECO-P02]** | P2 | TBD | Optimize SQLAlchemy async session scoped context. |
| `[ ]` | **[ECO-P03]** | P2 | TBD | Benchmark the CPU inference optimization picked in ECO-F07 (quantized/ONNX/JIT) against the plain fp32 model — p50/p99 latency and RSS memory — before it ships. See `strategy.md` §5/§7. |

## 🧪 Testing & Observability
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-T01]** | P2 | @Nazmul | Increase integration test coverage for ML registry. |
| `[ ]` | **[ECO-T02]** | P3 | TBD | Add Prometheus custom metrics for inference latency. |
| `[ ]` | **[ECO-T03]** | P1 | TBD | Add a `/health` (or `/v1/model-status`) endpoint reporting the currently-loaded model version, last successful reload time, and last reload failure if any — feeds the metrics in ECO-T02. |
| `[ ]` | **[ECO-T04]** | P2 | TBD | Integration test: point the model loader (ECO-F03) at a real (test) MLflow registry, register two model versions, and confirm hot-reload (ECO-F04) picks up the second without dropping in-flight requests. |

---

## 🔮 Forecasting Pipeline (Model Serving)
> `forecast-api` never trains — `data-pipeline` owns training, tuning, evaluation,
> conformal calibration, and MLflow registration end-to-end (root `TODO.md`
> ECO-108–119, `forecasting/mlops/registry.py` = ECO-115). This service's job is
> the "CPU-Edge" half of `strategy.md`'s hybrid pattern: load whatever model
> version is currently tagged `Production` in the MLflow Registry, serve it at
> low latency, and hot-swap in new versions without downtime. See `strategy.md`
> for the full design and open decisions (§7).
>
> Ordered so each item is buildable once the one before it lands. **Blocked**
> on `data-pipeline` shipping ECO-115 (registry) and ECO-114 (conformal
> intervals) — there is nothing to load or serve bands from until a model is
> actually registered there. No `src/` exists yet for this service; this is a
> from-scratch build, same as `data-pipeline`'s `forecasting/` tree.

| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-F02]** | P1 | TBD | Build this service's own `Settings` (own `config.py`, cached `get_settings()` — same pattern as `data-pipeline`'s, per root CLAUDE.md's config guidance): needs `mlflow_tracking_uri`, `model_stage` (default `"Production"`), `model_reload_interval_seconds`, `inference_device` (`"cpu"`), and a flag for whichever CPU optimization ECO-F07 picks. Do this first — everything below reads from it. |
| `[ ]` | **[ECO-F03]** | P1 | TBD | Build the Model Loader: pull the current `model_stage`-tagged version via `mlflow.pytorch.load_model(...)` against the registry, loading with `map_location=torch.device('cpu')` (strategy.md §3). Blocked on `data-pipeline` registering at least one model version (ECO-115). |
| `[ ]` | **[ECO-F04]** | P1 | TBD | Build hot-reload: poll the registry every `model_reload_interval_seconds` and atomically swap the in-memory model reference so in-flight requests never see a half-loaded model (strategy.md §4, "Synchronization"). Polling vs. a push signal from `data-pipeline` on promotion is still open — see strategy.md §7. |
| `[ ]` | **[ECO-F05]** | P1 | TBD | Build the sliding-window feature buffer (`collections.deque`, strategy.md §6) that reconstructs each request's `model_lookback`-length input window from already-ingested features, so `/v1/forecast` doesn't re-query Postgres per request. |
| `[ ]` | **[ECO-F06]** | P1 | TBD | Build the `POST /v1/forecast` endpoint: run the loaded model plus `data-pipeline`'s conformal calibration (ECO-114) to return point + P10/P50/P90 bands. This is the service's only public forecast contract — batch/offline scoring stays in `data-pipeline`'s `forecasting/serving/forecast.py` (ECO-117), not here. |
| `[ ]` | **[ECO-F07]** | P2 | TBD | Decide + implement one CPU inference optimization from strategy.md §5 (dynamic quantization, ONNX Runtime, or JIT trace) — pick based on the benchmark in ECO-P03, not all three. |
| `[ ]` | **[ECO-F08]** | P2 | TBD | Add rollback: if a newly-loaded model version fails a post-reload sanity check (e.g. NaN output, latency spike), keep serving the previous version and alert instead of swapping. Exact trigger condition is still open — strategy.md §7. |
| `[ ]` | **[ECO-F09]** | P3 | TBD | Once `data-pipeline` resolves root TODO ECO-118 (what "online learning" means — periodic fine-tune vs. scheduled full retrain), revisit `model_reload_interval_seconds`: a fine-tune-every-few-minutes design needs a much tighter reload loop than a nightly retrain does. |

---

## 📝 Developer Guidelines
1. **Link:** Every item must have a corresponding GitHub Issue.
2. **Format:** Use `[ECO-XXX]` in code comments to enable audit scripts.
3. **Definition of Done (DoD):**
    - Code change implemented and reviewed.
    - Associated unit/integration tests passed.
    - This file updated (Status moved to `[✓]`).
    - GitHub Issue closed.
    - `TODO` tag removed from source code.

---

## ✅ Recently Completed
- [✓] **[ECO-F00]** Setup baseline FastAPI project structure.
- [✓] **[ECO-F99]** Configure initial CI/CD pipeline.

### 🗂 Structure

_Auto-generated by `services/scripts/update_structure_todos.sh`. `[ ]` = empty stub file, `[x]` = has content. Re-run after adding/removing files to keep this current — do not hand-edit between the markers._

<!-- STRUCTURE:END -->
