# EcoLens Market Data — Step-by-Step Feature Selection Strategy

**Applies To**: LSTM, TFT, and TimesFM pipelines handling 5-minute NEM/WEM data.  
**Objective**: Systematically prune noise, handle multicollinearity, and isolate high-signal features without relying purely on intuition.

---

## Step 1: Data Pre-Filtering & Structural Hygiene
Before running statistical calculations, clean the raw feature pool from the warehouse:
1. **Remove Leakage & Identifiers**: Drop metadata fields that do not have predictive value or would cause data leakage (e.g.,  `source_url`, `fetched_at`).
2. **Handle Missing Values**: Impute or drop intervals with corrupted sensors or prolonged missing blocks.
3. **Variance Thresholding**: Drop any feature with zero variance or near-zero variance (e.g., `nuclear_mw` or `geothermal_mw` which remain at 0 in the NEM/WEM datasets).

---

## Step 2: Information-Theoretic Ranking (Mutual Information)
Run **Mutual Information (MI)** regression between all candidate time-varying features and the target (`demand_mw`):
* **Why**: It captures non-linear relationships and sudden market spikes (such as price and demand non-linear interactions) without assuming a linear correlation.
* **Action**: Rank all features by their MI score against `demand_mw`. Drop the bottom 15–20% of features that show near-zero dependency.

---

## Step 3: Time-Series Dependency Check (PACF & Lags)
For sequential models (LSTM and TimesFM), identify optimal historical lookback intervals:
* **Partial Autocorrelation Function (PACF)**: Analyze the PACF of `demand_mw` to isolate exact critical lag steps (e.g., lag 1 for 5 mins ago, lag 288 for 24 hours ago).
* **Action**: Construct explicitly validated lagged features for core drivers (`demand_mw`, `price_mwh`, `wind_mw`) based strictly on statistical cutoff thresholds rather than arbitrary history sizes.

---

## Step 4: Multicollinearity & Redundancy Pruning (SHAP + LightGBM)
Energy datasets contain heavily collinear variables (e.g., individual fuel types versus total generation mix). 
1. **Train a Proxy Model**: Fit a lightweight gradient boosting model (XGBoost) using  post-MI feature pool to predict `demand_mw`.
2. **Calculate TreeSHAP Values**: Compute global feature importance via SHAP to determine each variable's actual marginal contribution.
3. **Resolve Collinearity**: If two features are highly collinear (e.g., `total_generation_mw` and the sum of individual fuel types), retain the granular components (`coal_black_mw`, `wind_mw`, etc.) because models like TFT and LSTM benefit from granular fuel breakdowns. Drop redundant macro aggregates.

---

## Step 5: Automated Selection via TFT Variable Selection Networks
For the **Temporal Fusion Transformer**, utilize its native architecture as a final automated filter:
* **Action**: Feed the refined feature subset into the baseline TFT training loop. 
* **Evaluation**: Inspect the internal **Variable Selection Weights** outputted by the model's gating network. 
* **Final Cut**: Permanently drop any feature assigned a near-zero weight across all horizons by the TFT attention mechanism before locking in your production feature store.