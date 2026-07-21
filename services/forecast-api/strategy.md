# Strategy: Deploying Incremental LSTM Training

This strategy outlines the architecture for moving a GPU-trained PyTorch LSTM model to a CPU-only production environment for live incremental learning.

## 1. Overview
The primary goal is to ensure model portability and performance when transitioning from a GPU-accelerated training environment to a CPU-bound production server. We prioritize a hybrid deployment that keeps inference fast while enabling incremental learning.

## 2. Service Boundary: Who Does What
This repo already draws a hard line between the two services, and this strategy has to fit inside it rather than reopen it:

* **`services/data-pipeline`** owns training, tuning, evaluation, conformal calibration, and MLflow registration end-to-end (`forecasting/training/`, `forecasting/evaluation/`, `forecasting/mlops/registry.py`). It also owns whatever "incremental"/"online" training turns out to mean (`forecasting/training/online.py` — see root `TODO.md` ECO-118, still an open design decision, not yet built).
* **`services/forecast-api`** (this service) never trains. It only ever *loads* the version currently sitting in the MLflow Registry's `Production` stage and serves it at low latency.

So in the "Hybrid" pattern below (§4), the **Shadow Training (GPU-Worker)** is `data-pipeline`, and the **Synchronization** channel is the MLflow Model Registry (a version transitions to `Production`), not a raw shared volume or ad hoc file drop — this service polls/reacts to registry state, it does not receive weights directly from a training process. As of writing, `data-pipeline`'s `forecasting/` tree (including the registry client) is still an empty-stub scaffold (root `TODO.md` ECO-108–119), and this service has no `src/` yet — so everything here is forward-looking design, not a description of running code.

## 3. Model Portability Strategy
To move models between environments without retraining, we utilize `state_dict` serialization with explicit device mapping.

*   **Saving (GPU, in `data-pipeline`):**
    ```python
    torch.save(model.state_dict(), 'model_weights.pth')
    ```
*   **Loading (CPU, in this service):**
    ```python
    model.load_state_dict(torch.load('model_weights.pth', map_location=torch.device('cpu')))
    ```
* In practice this happens via `mlflow.pytorch.load_model(...)` against the registry rather than a bare file path, so the loader also gets model signature/version metadata for free — see ECO-F03.

## 4. Production Architecture: The "Hybrid" Pattern
If the CPU server is resource-constrained, we decouple the heavy training (gradient updates) from the light inference.

1.  **Inference (CPU-Edge, this service):** `forecast-api` performs lightweight inference using the latest `Production`-stage weights.
2.  **Shadow Training (GPU-Worker, `data-pipeline`):** `data-pipeline`'s training/online-learning process consumes the same feature stream and executes the `optimizer.step()` cycles, out of process from this service.
3.  **Synchronization:** `data-pipeline` promotes a challenger version to `Production` in the MLflow Registry (its promotion policy, ECO-115, decides *when*); `forecast-api` polls the registry on an interval and hot-swaps its in-memory model reference — see ECO-F04. No shared volume or custom RPC needed.

## 5. Performance Optimization for CPU
To ensure the model performs efficiently on CPU-only infrastructure:

*   **Dynamic Quantization:** Apply PyTorch's dynamic quantization to reduce memory overhead and improve throughput.
    *   *Implementation:* `model_int8 = torch.quantization.quantize_dynamic(model, {nn.LSTM, nn.Linear}, dtype=torch.qint8)`
*   **ONNX Runtime:** Convert the model to ONNX format for optimized inference execution.
*   **JIT Tracing:** Use `torch.jit.trace` to bypass Python interpreter overhead.
*   Pick **one** of these to start (ECO-F07) based on a latency/memory benchmark (ECO-P03), not all three — each adds its own conversion/compat risk and there's no evidence yet which one this model needs.

## 6. Incremental Learning Mechanics
The incremental learning logic must remain device-agnostic:

*   **Data Pipeline:** Maintain a `collections.deque` buffer on the CPU to sustain the sliding window required for LSTM time-series input (ECO-F05) — this reconstructs each request's `model_lookback`-length window from already-ingested features instead of re-querying Postgres per request.
*   **Handling Hidden States:** Ensure continuous hidden state tracking between steps to maintain temporal context.
*   **Concept Drift Management:** Feature/residual drift detection (PSI + KS test) lives in `data-pipeline`'s `forecasting/mlops/drift.py` (root TODO ECO-116) — this service does not compute drift itself. It only needs to react if `data-pipeline` demotes/rolls back the `Production` version, which the reload logic (ECO-F04/ECO-F08) already handles as a version change.

## 7. Open Decisions
These need an answer before (or while) building the corresponding TODO item — flagging them here so they don't get silently assumed:

* **Quantization vs. ONNX vs. JIT (ECO-F07):** which one, and on what benchmark basis (ECO-P03)?
* **Reload trigger (ECO-F04):** interval polling of the registry, or does `data-pipeline` push a signal/webhook on promotion? Polling is simpler and is the default assumption above; revisit if reload latency (time-to-serve after promotion) turns out to matter.
* **What "online learning" means (root TODO ECO-118, owned by `data-pipeline`):** a periodic fine-tune on the newest window, or a scheduled full retrain? This service's reload cadence (ECO-F09) depends on the answer — a fine-tune-every-few-minutes design needs a much tighter reload loop than a nightly retrain does.
* **Rollback trigger (ECO-F08):** what counts as a "bad" model version worth auto-rolling-back from — NaN outputs, a latency regression, or only an explicit demotion in the registry?

## 8. Summary Checklist
- [ ] Save model as `state_dict` (`data-pipeline`, ECO-112/ECO-115).
- [ ] Build forecast-api's own `Settings`/config (ECO-F02).
- [ ] Build the Model Loader against the MLflow Registry with `map_location=torch.device('cpu')` (ECO-F03).
- [ ] Build hot-reload / atomic model swap (ECO-F04).
- [ ] Use a sliding window (deque) for temporal consistency (ECO-F05).
- [ ] Ship the `/v1/forecast` endpoint with conformal P10/P50/P90 bands (ECO-F06).
- [ ] Pick and apply one CPU inference optimization, backed by a benchmark (ECO-F07/ECO-P03).
- [ ] Add rollback on a failed post-reload health check (ECO-F08).
- [ ] Resolve what "online learning" means with `data-pipeline` and adjust reload cadence accordingly (ECO-F09).
- [ ] Monitor CPU usage / reload health via Prometheus metrics (ECO-T02/ECO-T03).
