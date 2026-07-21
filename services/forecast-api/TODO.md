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
| `[ ]` | **[ECO-F01]** | P1 | @Nazmul | Implement circuit breaker for external AEMO API calls. |
| `[ ]` | **[ECO-F02]** | P2 | TBD | Transition from Gunicorn to Uvicorn worker lifecycle. |
| `[ ]` | **[ECO-F03]** | P2 | TBD | Implement structured logging (JSON) for OTel ingestion. |

## ⚡ Performance & Scalability
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-P02]** | P2 | TBD | Optimize SQLAlchemy async session scoped context. |

## 🔮 Forecasting
> `data-pipeline` owns model **training** + MLflow registration end-to-end
> (root `TODO.md`'s forecasting section); `forecast-api` only ever
> **loads and serves**. No model is registered yet, so `v1` ships a
> seasonal-naive baseline (`forecasting/baseline.py`) computed directly
> from `ml_features_demand_v1`'s precomputed lag columns -- a real,
> working default, not a stub.
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-F04]** | P1 | TBD | Swap the baseline forecaster for a real model loader once data-pipeline's training pipeline (root `TODO.md` `ECO-108`..`ECO-119`) registers a Production model in MLflow -- same `ForecastResponse` contract, no route change. |
| `[ ]` | **[ECO-F05]** | P2 | TBD | Once `ECO-114` (conformal calibration) lands upstream, replace the naive std-based P10/P90 band in `baseline.py`/the future model loader with real conformal intervals. |

## 🧪 Testing & Observability
| Status | ID | Priority | Owner | Description |
| :--- | :--- | :--- | :--- | :--- |
| `[ ]` | **[ECO-T01]** | P2 | @Nazmul | Increase integration test coverage for ML registry. |
| `[ ]` | **[ECO-T02]** | P3 | TBD | Add Prometheus custom metrics for inference latency. |

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
- [✓] **[ECO-P01]** Implement Redis caching layer for `/v1/forecast/{region}` (`cache.py`, wired into `routes.py`; no-ops safely when Redis is unconfigured/unreachable).