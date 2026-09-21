# Electricity Demand forecasting and carbon footprint Intelligence: High-Level Architecture & Technical Overview

This platform  is an end-to-end data engineering and machine learning system designed for energy grid intelligence and carbon accounting. The platform ingests real-time power system data, forecasts future energy demand with detailed source breakdowns (e.g., coal, gas, wind, solar), and translates those predictions into actionable environmental metrics (carbon intensity and total emissions).
What It Does
This Platform bridges the gap between power grid operations and environmental impact analysis by answering two critical questions:

The platform answers two key questions:
- How much electricity will be needed over the next 48 hours?
- How clean will that electricity be based on the expected generation mix?
It generates probabilistic demand forecasts (P10, P50, P90), predicts the contribution of different energy sources, and estimates future carbon intensity and emissions to support planning and sustainability analysis.


## How It Works: The Architecture Pipeline
Platform operates through a decoupled, event-driven data pipeline spanning ingestion, warehousing, predictive modeling, and carbon tracking:


1. Ingestion Pipeline
Mechanism :
Every  30 minutes, respective scheduled cron triggers dispatch asynchronous background tasks managed by Celery to ingest operational energy data from external REST APIs across their distinct polling intervals. The incoming payloads are safely captured and staged in a local DuckDB instance for normalization and preparation. Once processed, Celery publishes completion events via RabbitMQ to notify the downstream warehouse service for ingestion, ensuring a decoupled, event-driven architecture that provides a resilient foundation for warehousing, forecasting, and carbon accounting.

Storage:
To optimize infrastructure costs, the platform uses DuckDB as a lightweight, high-performance local staging database instead of writing every incoming record directly to the cloud data warehouse. DuckDB provides fast data ingestion and analytical querying with minimal resource overhead, making it well suited for high-frequency data collection. Once staged, the data is published to the event-driven warehousing pipeline for validation, transformation, and long-term storage in PostgreSQL.Finally all arteffects been stored in Cloudflare R2 storage.

2. Event-Driven Warehousing
Purpose
Operational data collected from external APIs is stored exactly as received, making it suitable for ingestion but not for analytics. To support accurate forecasting, carbon accounting, dashboards, and reporting, the platform consolidates, validates, and transforms this raw data into a structured, analytics-ready format. The data warehouse serves as the single source of truth for historical analysis and machine learning.
Mechanism:
Once new data has been successfully ingested in DuckDB, the platform publishes an event to RabbitMQ to notify the data warehouse that new data is ready for processing. This allows data ingestion and data warehousing to operate independently, so the platform can continue collecting new data without waiting for warehouse processing to complete. By decoupling these processes, the platform improves reliability, maintains consistent ingestion performance, and can scale more efficiently as data volumes increase.
Warehouse Pipeline:
When a RabbitMQ event is received, the warehousing service copies the staged data from DuckDB into the PostgreSQL raw.* schema, where the data is stored exactly as it was received from the external APIs. Keeping an unmodified copy of the raw data provides a reliable audit trail, making it possible to trace every record back to its original source, investigate data issues, and reprocess historical data whenever transformation rules change.
The platform uses PostgreSQL as its analytical warehouse because it provides a cost-effective, fully managed relational database that is well suited for the project's data volume and analytical workloads. Running on NeonDB's serverless PostgreSQL, the warehouse automatically scales with demand while avoiding the operational overhead and cost of managing dedicated database infrastructure. For a project of this size, a PostgreSQL-based warehouse offers an excellent balance of performance, flexibility, and cost. Although cloud-native warehouses such as Google BigQuery, Amazon Redshift, or Snowflake provide massive scalability, they are designed for much larger analytical workloads and would introduce unnecessary complexity and infrastructure costs for this platform.
Once the data is stored in PostgreSQL, the platform uses dbt (Data Build Tool) to transform the raw data into analytics-ready datasets. While these transformations could be written as standalone SQL scripts or custom Python programs, dbt provides a more maintainable and reliable engineering workflow. It organises SQL into modular, reusable models, automatically manages dependencies between transformations, includes built-in data quality tests and documentation, and integrates naturally with version control and CI/CD pipelines. As the data pipeline grows, this approach significantly reduces maintenance effort and improves the reliability and consistency of analytical data.
The resulting curated analytical tables provide a trusted foundation for forecasting models, carbon accounting, dashboards, and reporting.



Storage Policy:
Storage Policy
The platform adopts a layered storage strategy that balances cost, performance, and analytical flexibility. The PostgreSQL raw.* schema retains the complete historical copy of all ingested data exactly as received from external providers. Maintaining a full raw history ensures every record remains available for auditing, troubleshooting, data lineage, and reprocessing if transformation logic or business requirements change.
The platform also maintains curated analytical tables, which contain cleaned, standardised, and business-ready datasets generated by dbt. These tables retain the complete historical dataset required for forecasting, long-term trend analysis, carbon accounting, and reporting. By separating raw and curated data, the platform preserves the original source data while providing optimised datasets for analytics and machine learning.
DuckDB serves as a high-performance local analytical database within the data pipeline. It is used by the ingestion layer to store historical operational data locally and by the warehousing pipeline as the execution engine for dbt transformations before curated datasets are synchronised to PostgreSQL (NeonDB). This architecture enables fast local processing while leveraging a managed, serverless PostgreSQL warehouse for persistent storage and application access.


3. Predictive Modeling & Carbon Insights
Predictive Modeling:

Accurate electricity demand forecasting is essential for anticipating future energy requirements, estimating carbon emissions, and supporting operational planning. To maintain high accuracy in dynamic energy markets, the platform employs a robust online and incremental learning framework alongside its core multi-model architecture, allowing models to continuously adapt to evolving demand patterns and concept drift without requiring full retraining from scratch.

Adaptive AI Models: The platform uses a blend of specialized neural networks (LSTM and TFT) alongside Google's advanced time-series AI (TimesFM) using transfer learning. These models learn long-term patterns while continuously tweaking their internal weights using incoming streaming data to handle sudden load shifts and concept drift.
Smart Uncertainty Ranges (Probabilistic Forecasts): Rather than guessing a single fixed number, the models provide a range of outcomes—specifically P10, P50, and P90 estimates. This means it calculates conservative, expected, and peak demand scenarios so decision-makers can plan for best- and worst-case situations safely.
Auto-Correcting Accuracy: The platform uses automated safety checks (conformal calibration) to continuously monitor its own error rates. If forecasts start drifting off target, the system self-corrects its uncertainty ranges and seamlessly falls back to a reliable backup baseline model if any anomaly occurs.
Model Optimization & Efficiency: To ensure low-latency performance and a lightweight resource footprint, the platform applies **structured pruning** to remove redundant internal layers and connections from deep architectures. It then uses **fine-tuning** workflows to recover any predictive accuracy lost during the pruning phase prior to live production deployment.


Carbon Insights:
Forecasting electricity demand alone does not indicate the environmental impact of meeting that demand. The platform therefore combines demand forecasts with carbon intensity and renewable energy data obtained from external providers. This enables users to estimate future carbon emissions alongside future electricity demand, supporting sustainability reporting and operational decision-making.
Where renewable energy metrics are unavailable, the platform derives the renewable proportion from the observed electricity generation mix, ensuring carbon insights remain available even when external data is incomplete

Model Lifecycle Management:
Machine learning models continuously evolve as new data becomes available and forecasting performance improves. The platform uses MLflow to manage the complete model lifecycle, including experiment tracking, model versioning, artifact storage, validation, and deployment.
Although these tasks could be managed manually, MLflow provides a standardized and reproducible workflow. It records training parameters, evaluation metrics, datasets, and model artifacts for every experiment, making it easy to compare model versions, reproduce previous results, and safely promote validated models into production. This improves collaboration, simplifies model governance, and ensures consistent production inference.


4. 4. Observability
The platform uses a centralized observability service to monitor the independently maintained ingestion, warehouse, and forecast microservices without tightly coupling them or generating unnecessary service-to-service traffic.
Each microservice exposes standardized metrics, produces structured logs, and emits distributed traces through OpenTelemetry. An independent observability stack collects and aggregates this telemetry using OpenTelemetry Collector, Prometheus, Loki, and Tempo, while Grafana provides centralized dashboards and monitoring.
Telemetry is collected asynchronously or through periodic metric scraping, so the observability layer does not become part of the critical execution path of the business services. This enables independently operating each  service while providing centralized visibility into system health, pipeline failures, latency, resource usage, and forecasting performance.

5. Frontend Visualization & User Experience
Frontend:
The platform presents complex energy, forecasting, and sustainability data through a modern web application built with Next.js. Rather than requiring users to interpret raw datasets or API responses, the application provides an intuitive interface for exploring historical trends, monitoring real-time grid conditions, analysing demand forecasts, and understanding carbon emissions. Next.js was chosen because it offers excellent performance, server-side rendering, and a scalable architecture for building responsive, production-ready web applications while providing a seamless user experience across desktop and mobile devices.
Data Access:
To ensure the user interface remains decoupled from the underlying data processing pipeline, the frontend communicates exclusively with the backend through REST APIs. This allows the backend to independently manage data ingestion, warehousing, forecasting, and analytics while exposing a stable and consistent interface to the frontend. As new data becomes available, the frontend retrieves the latest operational data, forecasting results, and analytical insights without requiring direct access to the underlying databases or machine learning services.

Visualization:

Large volumes of operational and analytical data are easier to understand when presented visually rather than as tables or raw JSON. The platform therefore provides interactive dashboards, charts, maps, and forecasting visualisations that highlight key energy, weather, and carbon metrics. These visualisations enable users to identify trends, compare historical and predicted values, monitor system performance, and make informed operational and sustainability decisions more efficiently.
