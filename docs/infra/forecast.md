### Behind the Scenes: How EcoLens Turns a Warehouse Table Into a Forecast

Everything upstream in **EcoLens** exists to answer one core question: *What is the electricity grid likely to do next?*

The `forecast-api` service handles this task by training PyTorch models on cleaned historical demand data, serving live predictions, and monitoring forecast quality with built-in fallbacks.

---

### Feature Engineering Pipeline

Raw warehouse records from `raw_marts.fct_energy_demand` across six grid regions (NSW1, QLD1, VIC1, SA1, TAS1, WEM) are transformed via `ml/features.py` into six key input categories:

* **Market Context:** Real-time electricity demand, wholesale prices, total generation, and total renewables.
* **Weather Metrics:** Temperature, apparent temperature, humidity, wind speed, and **distance from 18°C** (capturing extreme heating/cooling demand).
* **Cyclical Calendar Encodings:** Sine/cosine-encoded hour-of-day and day-of-week signals to prevent artificial time boundaries, plus weekend and public holiday flags.
* **Cross-Region Context:** Total grid-wide demand and the current region's share of that total.
* **Explicit Region Identity:** One-hot encoding for target regions. *Without region identity, test error spiked to 76.79% (vs. 3.73% for single-region models) due to structural demand differences.*
* **Lags & Volatility:** Recent demand lags (t-1 to t-12) alongside rolling means and standard deviations over 6, 12, and 24-step windows.

---

### Model Architecture: The Production Pipeline

While EcoLens evaluates multiple architectures (including TFT, TimesFM, and multi-task LSTMs), the live endpoint strictly serves a single production-selected model: **DemandLSTM**.

```
[ Warehouse: fct_energy_demand ]
               │
               ▼
┌──────────────────────────────┐
│  Feature Engineering Pipeline│  <-- Market, Weather, Calendar, Lags, One-Hot Region
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  DemandLSTM Forward Pass     │
│  1. Two-Layer LSTM Encoder   │  <-- Learns temporal sequence representation
│  2. Attention Pooling        │  <-- Weights important timesteps dynamically
│  3. Three Prediction Heads   │  <-- Outputs P50, lower spread, upper spread
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Post-Model Calibration      │
│  • Per-Region Bias Offset    │  <-- Fits a single constant offset to fix bias
│  • Conformal Calibration     │  <-- CQR adjusts P10/P90 intervals dynamically
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Evaluation & MLflow Registry│  <-- Backtested against Seasonal-Naive baseline
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Serving & Safety Layer      │
│  • Production Pointer Swap   │  <-- Zero-downtime atomic model deployment
│  • Model Quality Circuit     │  <-- Trips to Seasonal-Naive if error spikes
└──────────────┬───────────────┘
               │
               ▼
[ GET /v1/forecast (Redis Cached) ]

```

---

### Key Architectural Decisions

* **Guaranteed Interval Ordering:** The `DemandLSTM` point head outputs median demand ($P_{50}$), while two softplus spread heads calculate lower and upper uncertainty bounds. This ensures $P_{10} \le P_{50} \le P_{90}$ by structural design.
* **Post-Model Calibration:** Predictions undergo two corrections before serving: a constant per-region bias offset (preventing up to 343 MW systematic shifts) and **Conformalized Quantile Regression (CQR)** to guarantee reliable uncertainty coverage.
* **Event-Driven Retraining:** Training runs inside a separate container triggered directly by warehouse completion events—ensuring models retrain only when fresh data lands.
* **Zero-Downtime Hot Swaps:** Models are evaluated via walk-forward backtests and manually promoted in MLflow. A background watcher executes an atomic pointer swap to update the active serving model without restarting the process.
* **Live Model Quality Circuit Breaker:** If live regional forecast accuracy drops below acceptable thresholds, a dedicated circuit breaker trips `GET /v1/forecast` to serve a simple **Seasonal-Naive baseline** for that region until recovery.

---

### Real-World Lessons: Two Technical Challenges Fixed

* **Overfitting Bias Corrections:** Initial attempts to eliminate regional prediction bias used separate Ridge regression models per region. However, limited calibration data caused overfitting. The fix was replacing complex models with a single, stable static offset per region.
* **Acknowledging Upstream Latencies:** Live demand charts update rapidly, but underlying AEMO historical training archives can lag by tens of hours. Rather than masking this discrepancy, EcoLens explicitly decouples real-time display metrics from model input freshness.

By coupling deep learning with rigorous post-processing calibration, fallback mechanisms, and zero-downtime serving, EcoLens produces forecasts that are both accurate and operationally dependable.