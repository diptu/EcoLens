# EcoLens Market Data — Model Training & Incremental Update Specification

**Schema Target**: `market_data.schema.json` (JSON Schema 2020-12)

**Applies To**: LSTM, Temporal Fusion Transformer (TFT), and TimesFM

**Schedule**: Monthly execution (1st of each month at 00:00 AEST) or triggered by admin anytime

---

## 1. Overview & Objectives

This document outlines the end-to-end operational specification for deploying, fine-tuning, and governing forecasting models handling **30-minute interval data** for the Australian National Electricity Market (NEM) and Wholesale Electricity Market (WEM).

The data pipeline ingests raw inputs from five core sources (`aemo_nem`, `aemo_wem`, `bom`, `openelectricity`, and `holidays`), processes and resamples them locally in **DuckDB**, and stores **only selected, curated features** in the **NeonDB (PostgreSQL)** cloud feature store for downstream model consumption.

---

## 2. Phase 1: Data Pipeline Bootstrap & Feature Store Ingestion

Before initiating baseline model training, raw inputs are harmonized onto a strict 30-minute temporal grid and synced to the cloud:

* **Local Preprocessing (DuckDB)**: Join all five sources, handle missing values (using OpenElectricity as a fallback without defaulting provisional values to zero), and align BoM weather observations and daily holiday markers onto a uniform 30-minute grid.
* **Feature Selection**: Project only necessary predictive columns (e.g., resampled demand, weather metrics, rolling statistics, and holiday flags) while discarding raw noisy logs.
* **NeonDB Sync**: Push only the curated 30-minute feature dataset into `model_feature_store` on NeonDB.
* **Baseline Bootstrap**: Models query historical records spanning up to 12 months directly from the NeonDB feature store to establish baseline weights.

---

## 3. Phase 2: Monthly Incremental Update Pipeline (1st of the Month)

On the 1st of every month, a scheduled background job queries a rolling historical window (the previous 6 to 12 months of 30-minute data) from NeonDB up to midnight of the prior day. Active production checkpoints are fine-tuned using model-specific protocols:

### 3.1 LSTM Fine-Tuning Protocol

* **State Loading**: Load the active production LSTM state dictionary (`model.load_state_dict(...)`).
* **Learning Rate**: Set a reduced learning rate ($5 \times 10^{-5}$ to $1 \times 10^{-4}$), significantly lower than the initial baseline training rate ($1 \times 10^{-3}$).
* **Execution**: Run **2 to 5 epochs** over the recent 30-minute data buffer to safely adjust weights without catastrophic forgetting.

### 3.2 Temporal Fusion Transformer (TFT) Fine-Tuning Protocol

* **State Loading**: Load the active production TFT checkpoint (`pytorch-forecasting` or `neuralforecast`).
* **Parameter Governance**:
* Static categorical attributes like `region` and `network_code` remain unchanged; freeze static embedding layers to preserve structural mappings.
* Apply a low global learning rate ($1 \times 10^{-5}$) across the network for **2 to 3 epochs** to allow self-attention decoders and variable selection weights to adapt smoothly to seasonal shifts.



### 3.3 TimesFM Fine-Tuning Protocol

* **State Loading**: Load the pretrained TimesFM checkpoint.
* **Execution**: Keep the core transformer backbone frozen. Fine-tune only the lightweight downstream projection head using the latest month's 30-minute streaming history for 1–2 epochs using a minimal learning rate.

---

## 4. Phase 3: Validation & Guardrails (The Safety Net)

To prevent data anomalies, corrupted metrics, or extreme price volatility spikes from injecting poor weights into production, candidate models must pass an automated validation gate prior to deployment.

```
[New Monthly 30-Min Data Buffer] ──> [Fine-Tune Candidate Model] 
                                            │
                                            ▼
                            [Run on Last 3–5 Days Holdout Set]
                                            │
                            ┌───────────────┴───────────────┐
                            ▼                               ▼
                 [Candidate Error <= Old?]         [Candidate Error > Old?]
                            │                               │
                            ▼                               ▼
                  (Promote to Production)          (Abort & Keep Existing Model)

```

1. **Holdout Selection**: Isolate the **last 3 to 5 days** of the expired month from the training pipeline to serve as an untouched validation holdout set.
2. **Error Calculation**: Evaluate both the active production model and the newly fine-tuned candidate model on this holdout window using Mean Absolute Error (MAE) or Root Mean Square Error (RMSE) against actual recorded 30-minute `demand_mw`.
3. **The Promotion Rule**:
* **Promote** the new checkpoint to live production *only if* $\text{MAE}_{\text{candidate}} \le \text{MAE}_{\text{production}}$.
* **Abort & Rollback**: If anomalies corrupt the recent training window and cause candidate model degradation, discard the candidate checkpoint immediately and maintain the existing production model.