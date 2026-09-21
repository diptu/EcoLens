# From Energy Data to Carbon-Aware Forecasts

Electricity demand is never static. It changes throughout the day, follows weekly routines, responds to weather, reacts to market conditions, and behaves differently across regions. For energy platforms, predicting that demand accurately is more than a data-science exercise. Forecasts influence how operators plan resources, how analysts understand market behavior, and how organizations estimate the environmental impact of electricity consumption.

This is the problem EcoLens is designed to address.

EcoLens is a near-real-time energy intelligence platform built around electricity-demand forecasting and carbon-aware analysis. It collects energy-market data, transforms it into structured time-series datasets, trains and evaluates multiple forecasting models, and exposes predictions through an API and dashboard.

The interesting part is not simply that EcoLens uses machine learning. It is that the platform combines several fundamentally different forecasting approaches and evaluates them through a common, reproducible framework.

Behind a single “next 24 hours of demand” chart are multiple models, data-processing stages, uncertainty estimates, monitoring mechanisms, and operational decisions.

This article explains how those pieces fit together.

---

## 1. From Raw Energy Data to Usable Time Series

A forecasting model cannot work directly with an uncontrolled stream of market data. Before any prediction can be generated, raw observations must be collected, validated, normalized, and transformed into a consistent time-series representation.

EcoLens integrates energy data from sources such as the Australian Energy Market Operator and OpenElectricity. The platform is designed to work with multiple electricity regions, including:

* New South Wales — NSW1
* Queensland — QLD1
* Victoria — VIC1
* South Australia — SA1
* Tasmania — TAS1
* Western Australia’s WEM/SWIS data where available

These regions differ in generation mix, demand patterns, weather conditions, and market behavior. A forecasting approach that performs well in one region may not perform equally well in another.

The data pipeline therefore has several responsibilities:

1. **Ingest new observations** at regular intervals.
2. **Normalize timestamps and regional identifiers.**
3. **Validate missing, duplicated, or abnormal records.**
4. **Build historical demand sequences.**
5. **Generate features used by forecasting models.**
6. **Store processed data for training, evaluation, and serving.**

The platform uses a combination of analytical and operational storage technologies, including DuckDB, PostgreSQL-based marts, Redis, and object storage. dbt transformations help organize the data into reusable analytical tables, while scheduled ingestion processes keep the system updated.

The goal is straightforward: every model should receive clean, consistently structured data, regardless of where that data originated.

---

## 2. Why EcoLens Uses Multiple Forecasting Models

There is no universally best forecasting model.

A simple statistical baseline can outperform a sophisticated neural network when demand is highly regular. A deep-learning model may capture nonlinear patterns that a seasonal baseline cannot. A foundation model may generalize surprisingly well without task-specific training, but still lack the domain-specific features required for production use.

For that reason, EcoLens includes four distinct forecasting approaches:

1. **Seasonal Naive** — a simple historical baseline.
2. **LSTM** — the current production deep-learning model.
3. **Temporal Fusion Transformer** — a more expressive architecture under evaluation.
4. **TimesFM** — a pretrained time-series foundation model used in zero-shot experiments.

All four models are evaluated through the same conceptual interface:

```python
predict(history, horizon) -> (p10, p50, p90)
```

Here:

* `history` is the observed historical demand.
* `horizon` is the number of future time steps to predict.
* `p50` is the central forecast.
* `p10` and `p90` represent lower and upper prediction bounds.

This common interface is important because it allows EcoLens to compare models fairly without requiring the rest of the application to understand each model’s internal architecture.

---

## 3. Seasonal Naive: The Baseline That Should Never Be Ignored

The Seasonal Naive model is intentionally simple.

Instead of learning a complicated relationship between dozens of features, it assumes that the future will resemble a corresponding period in the past.

For example, if electricity demand follows a strong weekly pattern, the forecast for Monday at 2:00 p.m. may begin with demand observed during a previous Monday at 2:00 p.m.

The model uses a configurable seasonal period based on the dataset’s sampling frequency. A seasonal period might represent:

* One day
* One week
* Another recurring operational cycle

For uncertainty estimation, the implementation can use historical residual behavior to construct a central forecast and prediction intervals. The result is exposed using the same approximate P10, P50, and P90 structure as the more advanced models.

### Why this model matters

A baseline provides an essential point of comparison.

Suppose an LSTM produces a lower error than Seasonal Naive. That suggests the neural network is learning something beyond ordinary repetition. But if the LSTM performs worse, the added complexity may not be justified.

The Seasonal Naive model is also useful as a fallback. If a machine-learning model fails a health check, produces invalid values, or encounters an unexpected input condition, a simple historical forecast may be safer than returning nothing.

### Its limitations

Seasonal Naive cannot naturally understand:

* Sudden structural changes
* Unusual weather conditions
* Market disruptions
* Long-term trends
* Complex interactions between external variables

It is not intended to be the most intelligent model. It is intended to be a reliable reference point.

In forecasting, simplicity is not the enemy. Unmeasured complexity is.

---

## 4. LSTM: The Current Production Forecaster

EcoLens’s current production deep-learning model is an LSTM-based architecture.

An LSTM, or Long Short-Term Memory network, is designed for sequential data. Unlike a conventional feed-forward network that treats each input independently, an LSTM processes observations in order and maintains internal representations of previous time steps.

This makes it suitable for electricity demand, where the current value depends partly on what happened earlier:

* Demand may rise after people wake up.
* Consumption may peak during working hours.
* Evening demand may follow a recurring pattern.
* A holiday may disrupt an otherwise familiar sequence.
* Recent demand may provide clues about the next few intervals.

### The encoder

The EcoLens LSTM uses a two-layer recurrent encoder.

The first LSTM layer processes the input sequence and produces hidden representations for each time step. The second LSTM layer processes those representations and learns a higher-level temporal representation.

The two layers are separate stages rather than one undifferentiated block:

```text
Historical sequence
        │
        ▼
LSTM Encoder Layer 1
        │
        ▼
LSTM Encoder Layer 2
        │
        ▼
Temporal representation
```

Stacking the layers allows the network to model temporal patterns at different levels of abstraction.

### Attention pooling

Instead of relying only on the final recurrent state, the model applies attention pooling over the encoded sequence.

This allows the network to assign different importance to different historical observations. For example, a recent demand spike, a similar time from the previous day, or a recurring weekly pattern may receive different weights depending on the context.

The resulting representation is passed to the forecasting heads.

### Quantile prediction heads

EcoLens does not only predict one number. It estimates a central forecast and uncertainty bounds.

The model uses separate heads for:

* A central point forecast
* A lower uncertainty component
* An upper uncertainty component

The output is transformed into prediction intervals using positive spread functions. Conceptually, the implementation follows this structure:

```text
P10 = point forecast - positive lower spread
P50 = point forecast
P90 = point forecast + positive upper spread
```

The use of a positive transformation, such as softplus, helps ensure that the predicted spreads remain non-negative.

This is important because energy forecasting is inherently uncertain. A model that predicts demand of 10,000 MW should also communicate how confident it is in that estimate.

### Training and calibration

The LSTM is trained using quantile-oriented objectives, including pinball loss, which is commonly used for probabilistic forecasting.

After training, conformal calibration can be applied to improve the reliability of prediction intervals. The objective is not merely to make the intervals mathematically wider or narrower, but to make them better aligned with observed forecast errors.

The model is also integrated with operational components such as:

* Region-specific preprocessing
* Feature scaling
* MLflow model tracking
* Forecast serving
* Monitoring and validation

### Why the LSTM is in production

The LSTM is currently the selected runtime model because it provides a practical balance between:

* Forecasting capability
* Computational cost
* Implementation maturity
* Serving simplicity
* Operational reliability

That does not mean it is permanently the best model. It means it is the model that has currently earned its place in the production pipeline.

---

## 5. Temporal Fusion Transformer: A More Expressive Alternative

The Temporal Fusion Transformer, or TFT, is a more complex forecasting architecture designed to combine several types of information:

* Historical time-series values
* Known future inputs
* Static features
* Variable importance
* Temporal dependencies

EcoLens includes a hand-rolled TFT implementation as an alternative to the LSTM.

The architecture contains several conceptual components.

### Variable selection

Different input variables do not contribute equally to every prediction. Variable-selection mechanisms attempt to learn which features are most useful in a given context.

For example, recent demand may be highly informative under normal conditions, while weather-related variables may become more important during extreme temperatures.

### LSTM encoder and decoder

Although the model is called a Transformer, TFT commonly combines recurrent components with attention mechanisms.

The recurrent encoder and decoder help represent local temporal dynamics, while attention can capture relationships across different positions in the sequence.

### Gated residual connections

Gated residual pathways allow the model to preserve useful information while controlling how much transformed information should be incorporated.

This can improve optimization and make complex architectures more stable.

### Static enrichment

TFT can incorporate static context, such as information about a region or asset.

In the current EcoLens implementation, the static enrichment pathway is present conceptually, but the static context is currently represented by a zero vector rather than a rich learned regional embedding. This means the architecture supports the mechanism, but the available static information is not yet being fully exploited.

### Interpretable self-attention

The attention mechanism is intended to help the model identify relationships between time steps. In principle, this can provide useful insight into which historical positions influence a forecast.

However, attention weights should not automatically be treated as definitive explanations. They are signals about the model’s internal computation, not guaranteed causal explanations.

### Current status

The TFT is trained and evaluated independently, but it is not currently the sole production-serving model.

This distinction matters.

A model can exist in the codebase, train successfully, and produce forecasts without being the model used by the live dashboard. Production serving requires additional confidence in:

* Accuracy
* Stability
* Latency
* Resource usage
* Failure behavior
* Monitoring
* Reproducibility

The TFT is therefore best understood as an active candidate for future production use rather than an already-deployed replacement for the LSTM.

---

## 6. TimesFM: Testing a Time-Series Foundation Model

The fourth approach is TimesFM, a pretrained time-series foundation model developed by Google.

Unlike the LSTM and TFT, which are trained or fine-tuned around EcoLens’s forecasting task, TimesFM is used primarily in a zero-shot or frozen-checkpoint configuration.

The idea behind a foundation model is that it may have learned broad temporal patterns from large-scale time-series data. Instead of training a new model from scratch for every dataset, users can test whether a pretrained model can generalize to a new forecasting problem.

In EcoLens, TimesFM is evaluated as an experimental forecasting option.

### Why it is interesting

A foundation model may offer:

* Strong general-purpose forecasting behavior
* Reduced task-specific training requirements
* A useful benchmark against custom architectures
* A way to test whether broad pretraining transfers to energy demand

### Why it is not automatically production-ready

TimesFM’s zero-shot setup has important limitations in the current system.

The model primarily receives raw demand history rather than the full set of domain-specific features available to EcoLens. That means it may not directly use:

* Weather forecasts
* Regional metadata
* Market-specific variables
* Carbon-intensity features
* Operational constraints

There are also practical considerations involving checkpoint loading, memory usage, inference latency, and model lifecycle management.

The model’s output format must also be adapted to EcoLens’s probabilistic forecasting interface so that it can be compared with models producing P10, P50, and P90 predictions.

TimesFM is therefore valuable as a research and benchmarking tool, but its presence does not imply that it is currently the production forecaster.

---

## 7. One Evaluation Harness for All Models

Comparing forecasting models is difficult if every model is evaluated differently.

A model may appear better simply because it receives more favorable data, uses a different test period, or benefits from information that would not be available at actual prediction time.

EcoLens addresses this by using a shared walk-forward evaluation approach.

### What is walk-forward evaluation?

In a walk-forward setup, the model is trained or fitted using historical data and then evaluated on a later period. The evaluation window moves forward through time.

Conceptually:

```text
Train on past → Predict the next period → Compare with reality
                     │
                     ▼
              Move the window forward
                     │
                     ▼
Train on more history → Predict again → Compare again
```

This better resembles real forecasting because the model only uses information that would have been available at the time of prediction.

### What is measured?

The evaluation process can compare:

* MAE — Mean Absolute Error
* RMSE — Root Mean Squared Error
* Quantile or pinball loss
* Prediction-interval coverage
* Forecast interval width
* Stability across regions
* Performance across different forecast horizons

The central forecast should be accurate, but uncertainty estimates should also be meaningful.

A model that has excellent P50 accuracy but produces unreliable P10 and P90 intervals may be less useful for operational planning than a slightly less accurate model with well-calibrated uncertainty.

### Why the common interface matters

Every model is evaluated through the same expected output:

```python
p10, p50, p90 = model.predict(history, horizon)
```

This makes it possible to compare different architectures without rewriting the evaluation system for each one.

The result is a more disciplined model-selection process:

* The Seasonal Naive model establishes the baseline.
* The LSTM demonstrates the current production level.
* The TFT tests whether a more expressive architecture provides measurable improvement.
* TimesFM tests whether pretrained generalization offers additional value.

The winning model should be selected based on evidence, not reputation or architectural novelty.

---

## 8. Why the Runtime Ensemble Was Not Automatically Used

The project previously explored an inverse-recent-error blending strategy, in which multiple models could be combined according to their recent performance.

In theory, model blending can be useful. If one model performs well during stable demand and another handles unusual patterns better, combining them may produce a more robust forecast.

However, an ensemble is not automatically better than its components.

A runtime ensemble introduces additional complexity:

* More models must be loaded.
* Inference becomes more expensive.
* Model failures become harder to isolate.
* Weight calculation must be monitored.
* Blending behavior must be validated.
* The ensemble may accidentally favor noisy short-term performance.

For that reason, the runtime ensemble is not currently treated as the default serving strategy. The platform instead uses a clearly selected production model while keeping alternative models available for controlled evaluation.

This is an important engineering principle: a feature should not be considered production-ready merely because it exists in the codebase.

---

## 9. Forecasting Is Also an Operational Reliability Problem

A forecasting model can be statistically strong and still fail as a production service.

Real-world systems must handle:

* Missing observations
* Delayed ingestion
* Unexpected timestamps
* Invalid values
* Model-loading failures
* Data-distribution changes
* Resource constraints
* API timeouts
* Regional outages

EcoLens therefore treats forecasting as a complete operational circuit rather than only a training task.

The broader platform includes components for:

* Scheduled ingestion
* Data transformation
* Model training
* Model registration
* Forecast serving
* Caching
* Monitoring
* Logging
* Metrics
* Tracing
* Alerting

A forecast is useful only when it is available at the right time, generated from valid inputs, and accompanied by enough information to understand its reliability.

A future improvement is to complete a forecast-quality circuit breaker that can detect when a model’s output is unsafe or unreliable and fall back to a simpler method.

For example, the system could reject a forecast if it contains:

* NaN or infinite values
* Negative demand where impossible
* Excessively wide uncertainty intervals
* Implausible jumps
* Severe drift from recent observations
* A failed model-health check

A fallback strategy should be explicit, tested, and observable rather than improvised during an outage.

---

## 10. What Comes Next?

EcoLens’s current architecture creates several clear directions for future development.

### A decisive LSTM-versus-TFT comparison

The next major question is whether the TFT provides enough improvement to justify its additional complexity.

That comparison should include not only average error, but also:

* Regional performance
* Extreme-demand periods
* Forecast horizons
* Calibration quality
* Inference cost
* Operational stability

If the TFT does not produce meaningful gains, the simpler LSTM may remain the better production choice.

### Future weather forecasts

Historical weather features can improve demand forecasting, but production forecasting requires future weather estimates, not merely weather observations from the past.

Integrating weather forecasts could help the models anticipate demand changes caused by:

* Heat waves
* Cold periods
* Storms
* Seasonal transitions
* Unusual temperature patterns

### Better use of TimesFM

TimesFM could become more useful if the system develops a stronger strategy for incorporating external covariates or adapting the model to energy-specific data.

This would require careful evaluation rather than assuming that a foundation model will automatically outperform a specialized model.

### Improved uncertainty calibration

Prediction intervals should be evaluated continuously. The platform can monitor whether observed outcomes fall within expected ranges and whether the intervals are too narrow or unnecessarily wide.

Reliable uncertainty is particularly important for carbon-aware decision-making, where users may need to understand not only the expected demand but also the range of plausible outcomes.

### Stronger model governance

As more models are trained and evaluated, EcoLens will benefit from clearer governance around:

* Model versions
* Training datasets
* Feature definitions
* Evaluation windows
* Promotion criteria
* Rollback procedures
* Production ownership

This makes the forecasting system easier to reproduce, debug, and improve.

---

## Conclusion: Forecasting Should Be Earned

EcoLens is not built around the assumption that the newest or most complicated model must be the best one.

Its forecasting architecture deliberately combines a simple baseline, a production LSTM, a more advanced Temporal Fusion Transformer, and a pretrained foundation model. Each approach offers a different trade-off between simplicity, expressiveness, generalization, uncertainty estimation, and operational cost.

The Seasonal Naive model establishes what can be achieved through recurring historical patterns. The LSTM provides a practical production solution for sequential demand forecasting. The TFT explores whether richer feature selection and attention mechanisms can deliver measurable gains. TimesFM tests whether broad pretrained temporal knowledge can transfer to the energy domain.

The common evaluation interface and walk-forward testing process make these comparisons meaningful. The production pipeline then adds the less glamorous but equally important work of validation, monitoring, caching, model management, and fallback behavior.

Ultimately, a forecasting model should not enter production because it is fashionable, complex, or impressive on paper.

It should enter production because it has demonstrated that it can produce useful predictions, communicate uncertainty honestly, operate reliably, and improve the decisions the platform is designed to support.

That is the standard EcoLens is working toward: not just predicting energy demand, but building a dependable foundation for carbon-aware energy intelligence.
