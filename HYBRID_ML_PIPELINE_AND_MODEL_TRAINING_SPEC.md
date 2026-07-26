# EcoLens — Hybrid ML Pipeline & Model Training Spec

> 30-min unified feature store, monthly fine-tuning of LSTM/TFT/TimesFM, and decoupled JSON serving.

---

## Architecture
5 sources (AEMO NEM, AEMO WEM, BoM, OpenElectricity, Holidays) → DuckDB preprocessing on a 30-min temporal spine → NeonDB feature store → 3 model families fine-tuned monthly → decoupled JSON output.

## Temporal Spine
| Region | Interval | Notes |
|---|---|---|
| `NSW1`, `QLD1`, `VIC1`, `SA1`, `TAS1` (NEM) | 30-min | AEMO 5-min downsampled |
| `WEM` (Western Australia) | 30-min | Single region, 5-min WEMDE downsampled |
| **Start** | 2025-08-01 | Master timeline start |

## 6-Step Preprocessing & Statistical Feature Selection (DuckDB → NeonDB)
1. **Build 30-min spine** per region from Aug 2025.
2. **Downsample 5-min AEMO** → 6 obs/interval (mean/total for energy; average/final for instantaneous).
3. **Map 30-min BoM directly** (no interpolation).
4. **Broadcast daily holidays** → intervals inherit `is_public_holiday`.
5. **Feature Engineering & Rigorous Statistical Selection**:
   - **Generation & Engineering:** Lags (1, 2, 48, 336), rolling stats (mean, median, max, min, std). Drop raw logs.
   - **Step 1: Structural Hygiene:** Drop leakage/metadata fields (`ingest_run_id`, etc.), handle missing blocks, and prune zero-variance features (`nuclear_mw`, `geothermal_mw`).
   - **Step 2: Information-Theoretic Ranking:** Compute **Mutual Information (MI)** regression against `demand_mw` to capture non-linear market spikes; drop the bottom 15–20% near-zero dependency features.
   - **Step 3: Time-Series Dependency (PACF):** Analyze the **Partial Autocorrelation Function** of `demand_mw` to isolate statistically validated lag steps rather than arbitrary windows.
   - **Step 4: Multicollinearity Pruning (TreeSHAP + LightGBM):** Fit a proxy LightGBM model, compute global **TreeSHAP** importance, and drop redundant macro aggregates while retaining granular fuel types.
   - **Step 5: Automated TFT Gating:** Feed features into the TFT and evaluate internal **Variable Selection Network weights** to permanently drop features with near-zero attention across all horizons.
6. **Sync to NeonDB** `model_feature_store` (PostgreSQL) — curated table only.

**Data & Missing-Value Guardrails:** 
- Never auto-replace nulls with zero (especially `renewable_proportion`). 
- OpenElectricity serves as fallback if AEMO is missing.

---

## Models & Schedule
| Model | Baseline | Monthly fine-tune | Backbone | Head |
|---|---|---|---|---|
| **LSTM** | LR=1e-3 | LR=5e-5 → 1e-4, 2-5 epochs | full | full |
| **TFT** | full | LR=1e-5, 2-3 epochs, **freeze static embeddings** (region, network_code) | VSN + attention + decoder | adapts |
| **TimesFM** | full | LR=very small, 1-2 epochs, **transformer frozen** | frozen | head only |

**Schedule:** Auto 1st of every month at 00:00 AEST (or manual via admin API).

---

## Monthly Fine-Tune & Validation Flow
```
[New 30-min data buffer] → [Fine-tune candidate] → [Holdout: last 3-5 days] 
                                                        ↓
                                                MAE ≤ production?
                                                  ↙         ↘
                                            (Yes: Promote)  (No: Rollback)
```
* **Metrics:** MAE + RMSE on `demand_mw`. 
* **Guardrails:** Candidate promoted only if $MAE_{candidate} \le MAE_{production}$ on the untouched holdout set; else rejected/rolled back.

---

## JSON Output — Decoupled Multi-Model Pipeline
| JSON Field | Model / Engine | Output & Reconciliation |
|---|---|---|
| `total_demand_mw.p10/p50/p90` | TFT/LSTM/TimesFM with **quantile loss** | Probabilistic bounds (optimistic / median / peak-risk) |
| `source_breakdown_mw` (16 fuel types) | LightGBM ensemble per fuel + BoM + holidays | Per-fuel MW; **normalized** via constraint layer so $\sum \text{source\_breakdown} \approx \text{total\_demand\_mw.p50}$ |
| `carbon_metrics` | **Non-ML deterministic** (IPCC AR5 + AEMO NGES) | `predicted_total_carbon_kgco2e`, intensity, and renewable proportion |
| `weather_context` | BoM live (no forecasting) | Current temp, humidity, wind for explainability |

---

## Data Sources (5) & Storage
* **Sources:** AEMO NEM (5-min, 2009+), AEMO WEM (5-min, 2012+), BoM (30-min, 1940+), OpenElectricity (5-min fallback), AU Public Holidays.
* **Storage:** DuckDB (local preprocessing), NeonDB PostgreSQL (`model_feature_store`), PostgreSQL `ecolens` DB (`market_data`, `weather`, `calendar`), MLflow SQLite registry (`/var/lib/ecolens/mlflow.db`).


eatures for the forecasting models are selected and refined through a rigorous 5-step statistical approach during preprocessing in DuckDB before syncing to the NeonDB feature store:

Step 1: Structural Hygiene: Drop metadata/leakage fields (such as ingest_run_id), handle missing blocks, and prune zero-variance features (like nuclear_mw or geothermal_mw).

Step 2: Information-Theoretic Ranking: Compute Mutual Information (MI) regression against demand_mw to capture non-linear relationships and market spikes, dropping the bottom 15–20% of features with near-zero dependency.

Step 3: Time-Series Dependency (PACF): Analyze the Partial Autocorrelation Function (PACF) of demand_mw to isolate statistically validated lag steps (e.g., lags 1, 2, 48, 336) instead of arbitrary windows.

Step 4: Multicollinearity Pruning (TreeSHAP + LightGBM): Fit a proxy LightGBM model, compute global TreeSHAP importance, and drop redundant macro aggregates while retaining granular fuel types.

Step 5: Automated TFT Gating: Feed features into the Temporal Fusion Transformer and evaluate internal Variable Selection Network weights to permanently drop features carrying near-zero attention across all horizons.