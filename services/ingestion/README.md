# 🔌 Ingestion Microservice

> Automated high-frequency energy data collection, real-time anomaly detection, and staging pipeline.

---

## 🔄 Ingestion Pipeline

The microservice runs an automated cron task in a predefiend interval to pull operational energy data from external provider REST APIs.

```text
[ External APIs ] ──> [ Anomaly Detection ] ──> [DuckDB Storage ]  ──> [ Event Pipeline ]
                                                                             │
                                                     ┌───────────────────────┴───────────────────────┐
                                                     ▼                                               ▼
                                             [ PostgreSQL ]                                  [ Cloudflare R2 ]
                                            (Long-term Storage)                             (Artifact Storage)
```

---

## 🛡️ Anomaly Detection Layer

Ingested data is processed through a **hybrid detection model** (Rules-based + Machine Learning) to differentiate between data glitches and actual grid events.

* **Identified Issues:** Sensor failures, API dropouts, demand spikes, and unexpected generation shifts.
* **Non-Destructive Flagging:** Records are **never deleted**. Each record receives an `anomaly_score` and an `explanation` to preserve raw historical data for downstream forecasting and carbon accounting.

---

## 💾 Storage Architecture

| Component | Role | Description |
| :--- | :--- | :--- |
| **DuckDB** | Local storage | Lightweight, embedded DB optimized for high-frequency analytical staging and low resource overhead. |
| **PostgreSQL** | Warehouse | Long-term data store fed by the event-driven pipeline after validation and transformation. |
| **Cloudflare R2** | Artifact Storage | Low-cost object storage for system artifacts and raw export archives. |