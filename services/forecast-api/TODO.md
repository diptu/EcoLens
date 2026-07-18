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
| `[ ]` | **[ECO-P01]** | P1 | TBD | Implement Redis caching layer for `/forecast/latest`. |
| `[ ]` | **[ECO-P02]** | P2 | TBD | Optimize SQLAlchemy async session scoped context. |

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