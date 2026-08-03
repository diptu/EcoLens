
# Electricity Demand forecasting and carbon footprint Intelligence: High-Level Architecture & Technical Overview

This platform  is an end-to-end data engineering and machine learning system designed for energy grid intelligence and carbon accounting. The platform ingests real-time power system data, forecasts future energy demand with detailed source breakdowns (e.g., coal, gas, wind, solar), and translates those predictions into actionable environmental metrics (carbon intensity and total emissions).

## What Platform Actually Achieves

This Platform bridges the gap between power grid operations and environmental impact analysis by answering two critical questions:
- What will energy demand look like in the near future (e.g., 24-hour horizon at 30-minute resolutions)?
- How clean will that energy be based on the predicted generation mix (renewable proportion vs. fossil fuels)?

The platform produces granular outputs containing probabilistic demand estimates (P10 = 10% chance of being this low or lower, P50 = the expected/median case, P90 = 90% chance of being this low or lower), granular fuel-source allocations (coal, gas, wind, solar, hydro, battery, ...), and derived carbon intensity factors (gCO₂e per MWh).


## How It Works: The Architecture Pipeline
The platform operates through a decoupled, event-driven data pipeline spanning ingestion, warehousing, predictive modeling, and carbon tracking. *(Target design — see `TODO.md`'s Ingestion/Warehouse sections for exactly what's built vs. still pending.)*


1. *Ingestion Pipeline*
*Mechanism:* 
Every 5 minutes, the platform automatically runs a scheduled task (cron job) to collect the latest operational energy data from external providers via REST APIs. The incoming data is stored in a local staging database (DuckDB), where it is prepared for downstream processing. This automated process ensures the platform continuously captures fresh operational data while providing a reliable foundation for warehousing, forecasting, and carbon accounting.

*Anomaly Detection Layer:* 
Energy systems occasionally produce unusual readings. Some are caused by sensor failures, communication issues, or incomplete API responses, while others represent genuine operational events such as sudden spikes in electricity demand or unexpected changes in renewable generation. To help distinguish between these scenarios, every ingested record is analysed using a hybrid anomaly detection approach that combines rule-based checks with machine learning models. Rather than removing suspicious records, the platform flags them with an anomaly score and explanation, enabling downstream systems and users to differentiate between data quality issues and real-world grid events while preserving valuable historical data. *(Planned — not yet implemented; see `TODO.md`'s Ingestion section.)*

*Storage:*
To optimize infrastructure costs, the platform uses DuckDB as a lightweight, high-performance local staging database instead of writing every incoming record directly to the cloud data warehouse. DuckDB provides fast data ingestion and analytical querying with minimal resource overhead, making it well suited for high-frequency data collection. DuckDB is embedded and file-backed — it runs in-process with no separate database server, so no MongoDB or MinIO/S3 dependency is needed for this staging layer. Once staged, the data is published to the event-driven warehousing pipeline for validation, transformation, and long-term storage in PostgreSQL.

2. *Event-Driven Warehousing*
*Purpose*
Operational data collected from external APIs is stored exactly as received, making it suitable for ingestion but not for analytics. To support accurate forecasting, carbon accounting, dashboards, and reporting, the platform consolidates, validates, and transforms this raw data into a structured, analytics-ready format. The data warehouse serves as the single source of truth for historical analysis and machine learning.
*Mechanism:* 
Once new data has been successfully ingested in DuckDB, the platform publishes an event to RabbitMQ to notify the data warehouse that new data is ready for processing. This allows data ingestion and data warehousing to operate independently, so the platform can continue collecting new data without waiting for warehouse processing to complete. By decoupling these processes, the platform improves reliability, maintains consistent ingestion performance, and can scale more efficiently as data volumes increase.
*Warehouse Pipeline:*
When a RabbitMQ event is received, the warehousing service copies the staged data from DuckDB into the PostgreSQL raw.* schema, where the data is stored exactly as it was received from the external APIs. Keeping an unmodified copy of the raw data provides a reliable audit trail, making it possible to trace every record back to its original source, investigate data issues, and reprocess historical data whenever transformation rules change.
The platform uses PostgreSQL as its analytical warehouse because it provides a cost-effective, fully managed relational database that is well suited for the project's data volume and analytical workloads. Running on NeonDB's serverless PostgreSQL, the warehouse automatically scales with demand while avoiding the operational overhead and cost of managing dedicated database infrastructure. For a project of this size, a PostgreSQL-based warehouse offers an excellent balance of performance, flexibility, and cost. Although cloud-native warehouses such as Google BigQuery, Amazon Redshift, or Snowflake provide massive scalability, they are designed for much larger analytical workloads and would introduce unnecessary complexity and infrastructure costs for this platform.
Once the data is stored in PostgreSQL, the platform uses dbt (Data Build Tool) to transform the raw data into analytics-ready datasets. While these transformations could be written as standalone SQL scripts or custom Python programs, dbt provides a more maintainable and reliable engineering workflow. It organises SQL into modular, reusable models, automatically manages dependencies between transformations, includes built-in data quality tests and documentation, and integrates naturally with version control and CI/CD pipelines. As the data pipeline grows, this approach significantly reduces maintenance effort and improves the reliability and consistency of analytical data.
The resulting curated analytical tables provide a trusted foundation for forecasting models, carbon accounting, dashboards, and reporting.



*Storage Policy:*

The platform adopts a layered storage strategy that balances cost, performance, and analytical flexibility. The PostgreSQL raw.* schema retains the complete historical copy of all ingested data exactly as received from external providers. Maintaining a full raw history ensures every record remains available for auditing, troubleshooting, data lineage, and reprocessing if transformation logic or business requirements change.
The platform also maintains curated analytical tables, which contain cleaned, standardised, and business-ready datasets generated by dbt. These tables retain the complete historical dataset required for forecasting, long-term trend analysis, carbon accounting, and reporting. By separating raw and curated data, the platform preserves the original source data while providing optimised datasets for analytics and machine learning.
DuckDB serves as a high-performance local analytical database within the data pipeline. It is used by the ingestion layer to store historical operational data locally and by the warehousing pipeline as the execution engine for dbt transformations before curated datasets are synchronised to PostgreSQL (NeonDB). This architecture enables fast local processing while leveraging a managed, serverless PostgreSQL warehouse for persistent storage and application access. DuckDB (embedded, file-backed) and PostgreSQL (managed, serverless) are the only two databases this pipeline depends on — no MongoDB or MinIO/S3 dependency is required anywhere in ingestion or warehousing.


3. Predictive Modeling & Carbon Insights
*Predictive Modeling:* 

Accurate electricity demand forecasting is essential for anticipating future energy requirements, estimating carbon emissions, and supporting operational planning. To maintain high accuracy in dynamic energy markets, the platform employs a robust online and incremental learning framework alongside its core multi-model architecture, allowing models to continuously adapt to evolving demand patterns and concept drift without requiring full retraining from scratch.

Adaptive AI Models: The platform uses a blend of specialized neural networks (LSTM and TFT) alongside Google's advanced time-series AI (TimesFM). These models learn long-term patterns while continuously tweaking their internal weights using incoming streaming data to handle sudden load shifts and concept drift.


Smart Uncertainty Ranges (Probabilistic Forecasts): Rather than guessing a single fixed number, the models provide a range of outcomes—specifically P10, P50, and P90 estimates. This means it calculates conservative, expected, and peak demand scenarios so decision-makers can plan for best- and worst-case situations safely.
Auto-Correcting Accuracy: The platform uses automated safety checks (conformal calibration) to continuously monitor its own error rates. If forecasts start drifting off target, the system self-corrects its uncertainty ranges and seamlessly falls back to a reliable backup baseline model if any anomaly occurs.


*Carbon Insights:* 
Forecasting electricity demand alone does not indicate the environmental impact of meeting that demand. The platform therefore combines demand forecasts with carbon intensity and renewable energy data obtained from external providers. This enables users to estimate future carbon emissions alongside future electricity demand, supporting sustainability reporting and operational decision-making.
Where renewable energy metrics are unavailable, the platform derives the renewable proportion from the observed electricity generation mix, ensuring carbon insights remain available even when external data is incomplete

*Model Lifecycle Management:*
Machine learning models continuously evolve as new data becomes available and forecasting performance improves. The platform uses MLflow to manage the complete model lifecycle, including experiment tracking, model versioning, artifact storage, validation, and deployment.
Although these tasks could be managed manually, MLflow provides a standardized and reproducible workflow. It records training parameters, evaluation metrics, datasets, and model artifacts for every experiment, making it easy to compare model versions, reproduce previous results, and safely promote validated models into production. This improves collaboration, simplifies model governance, and ensures consistent production inference.


4. Frontend Visualization & User Experience 
*Frontend:* 
The platform presents complex energy, forecasting, and sustainability data through a modern web application built with Next.js. Rather than requiring users to interpret raw datasets or API responses, the application provides an intuitive interface for exploring historical trends, monitoring real-time grid conditions, analysing demand forecasts, and understanding carbon emissions. Next.js was chosen because it offers excellent performance, server-side rendering, and a scalable architecture for building responsive, production-ready web applications while providing a seamless user experience across desktop and mobile devices.
*Data Access:* 
To ensure the user interface remains decoupled from the underlying data processing pipeline, the frontend communicates exclusively with the backend through REST APIs. This allows the backend to independently manage data ingestion, warehousing, forecasting, and analytics while exposing a stable and consistent interface to the frontend. As new data becomes available, the frontend retrieves the latest operational data, forecasting results, and analytical insights without requiring direct access to the underlying databases or machine learning services.

*Visualization:*

Large volumes of operational and analytical data are easier to understand when presented visually rather than as tables or raw JSON. The platform therefore provides interactive dashboards, charts, maps, and forecasting visualisations that highlight key energy, weather, and carbon metrics. These visualisations enable users to identify trends, compare historical and predicted values, monitor system performance, and make informed operational and sustainability decisions more efficiently.



To ensure that performing online or incremental training does not block core functionalities (such as real-time API responses, inference requests, or data ingestion pipelines), you need to decouple the heavy computational workload from the main application thread.

Here is how you can achieve a non-blocking architecture for incremental training:

1. Asynchronous Task Queues & Workers
Offload to Background Workers: Never run training loops synchronously inside your web server or API request-response cycle (e.g., FastAPI, Express, Flask). Instead, use a distributed task queue like Celery, RQ (Redis Queue), or Temporal powered by a message broker (RabbitMQ or Redis).

Execution Flow: When the forecasting service consumes the training trigger event from RabbitMQ, it pushes the training task to an asynchronous worker pool. The API server instantly returns an acknowledgment while the worker handles the heavy training loop in the background.

2. Dedicated Compute Infrastructure & Hardware Isolation
Separate Resource Pools: Isolate your training workers from your inference and API servers.

Resource Allocations: Run your API and inference services on CPU/GPU nodes optimized for low-latency responses, while routing training jobs to dedicated worker nodes equipped with the appropriate hardware (e.g., specific GPUs or scaled CPU cores) so that high memory or compute usage during training doesn't starve the API of resources.

3. Thread & Process Management for Lightweight Tasks
Process Forking / Multiprocessing: If you aren't using a heavy distributed queue and are running a local Python worker, use Python's multiprocessing module or asynchronous coroutines (asyncio) to run the model updates in a separate system process rather than a blocking thread. This prevents Python's Global Interpreter Lock (GIL) from freezing your application logic.

4. Thread-Safe Model Hot-Swapping (Zero-Downtime Updates)
Atomic Model Replacement: While incremental training updates the weights of models like LSTM, TFT, or TimesFM, your live inference service still needs to serve predictions using the current stable model weights.

In-Memory Swapping:

Train the model weights in a sandbox or a separate memory space.

Save or export the updated weights/artifact to a local cache or shared volume (managed via MLflow).

Use an atomic pointer swap or thread-safe reference assignment in your inference application to point to the new weights instantly, avoiding read/write locks or restarting the server.

5. Non-Blocking Data Access 
Incremental Batch Fetching (Pagination / Time-Bounds):
Instead of pulling massive blocks of history all at once, training queries to fetch only the precise time window needed for the incremental step (e.g., the last 5 minutes or the latest batch ID) using proper database indexes.
Use efficient, indexed queries bounded by timestamps or batch IDs to limit memory overhead when pulling training subsets.


Resource Management on Edge or Worker Nodes: Incremental training often happens frequently in the background on worker nodes. Keeping the model size optimized ensures that these recurrent weight updates and forward-backward passes consume minimal memory and CPU/GPU compute.

Maintaining Efficiency Post-Adaptation: As adaptive models (like LSTM, TFT, or TimesFM) continuously tweak their weights using incoming streaming data, applying structured pruning and periodic fine-tuning ensures that redundant pathways created or emphasized during continuous updates are pruned, preventing model bloat over time.

Balancing Plasticity and Stability: Fine-tuning during incremental updates helps the model absorb new data (plasticity) without forgetting previously learned patterns or drifting away from its optimized baseline structure (stability).


Capability / Resource,system_admin,admin,viewer
Infrastructure / Core Services (services:*),Allow,Deny,Deny
Root Secrets & Global Policies,Allow,Deny,Deny
Manage Users & Permissions,Allow,Allow (Restricted),Deny
"Trigger Runs, Backfills, Retraining",Allow,Allow,Deny
Promote Models & Approve Tasks,Allow,Allow,Deny
Read Data / Models / Runs / Reports,Allow,Allow,Allow
Export Data,Allow,Allow,Allow