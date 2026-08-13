# FastAPI Production Master Skill & Best Practices

A practical guide to building scalable, secure, high-performance, and production-ready FastAPI applications.

---
- **Execution**: Run `/fastapi <service_name>`.
## 0: Organize the Project as Independent Services

As the application grows, organize it into **domain-oriented services**. Each service owns its APIs, business logic, models, repositories, schemas, tests, documentation, and TODOs.

## 0: Organize the Project as Independent Services

As the application grows, organize it into **domain-oriented services**. Each service owns its APIs, business logic, models, repositories, schemas, tests, documentation, and TODOs.

### Strategic Import Organization

To maintain clean, readable, and manageable codebases, follow these practices:

1. **The "Barrel" Pattern**: Use `__init__.py` files to export public-facing modules. This allows you to consolidate deep import paths into a single, clean import statement.
2. **`TYPE_CHECKING` for Circular Dependencies**: Isolate type imports within `if TYPE_CHECKING:` blocks to ensure imports are only processed during static analysis, not at runtime.
3. **Automated Sorting**: Use **Ruff** (configured in `pyproject.toml`) to enforce import order (Standard Library, Third-Party, Local Application).
4. **Service-First Refactoring**: If a file exceeds 15 imports, it is a "code smell." Refactor into smaller domain modules or use Dependency Injection to reduce logic complexity in route handlers.


### Service Responsibilities

Each service should own:

* API routes
* Business logic
* Database models
* Repository layer
* Pydantic schemas
* Validation
* Dependencies
* Domain events
* Tests
* Documentation
* TODO list

Avoid placing unrelated business logic into another service.

### Shared Components

Only reusable, cross-cutting code belongs in shared locations.

Examples include:

* Common DTOs
* Pagination
* Generic validators
* Utility functions
* Shared enums
* Shared constants

Business-specific code should never live in shared modules.

### Documentation

Every service should include:

```text
README.md
```

Describing:

* Purpose
* Responsibilities
* API endpoints
* Dependencies
* Events
* Architecture

and

```text
TODO.md
```

Containing:

* Current tasks
* Planned work
* Technical debt
* Future enhancements

The project-level `TODO.md` should be generated automatically by aggregating all service TODO files:

```bash
python scripts/todo_manager.py --sync
```

### Development Workflow

For every new service:

1. Create the service directory.
2. Create the standard folder structure.
3. Write `README.md`.
4. Create `TODO.md`.
5. Register API routes.
6. Implement models.
7. Implement repositories.
8. Implement business services.
9. Implement schemas.
10. Implement validators.
11. Write unit and integration tests.
12. Register seed data.
13. Update documentation.
14. Synchronize the master TODO.

```bash
python scripts/todo_manager.py --sync
```

# 1. Concurrency Architecture & Async Rules

## Rule 1: Never Use `async def` for Blocking Operations

### Anti-Pattern

Running blocking operations inside an `async def` endpoint blocks the event loop and destroys concurrency.

Examples:

* `time.sleep()`
* `requests`
* Synchronous database drivers (`psycopg2`, `pymongo`)
* CPU-intensive operations

```python
@app.get("/users")
async def get_users():
    time.sleep(2)  # Blocks the event loop
```

### Production Practice

Use standard `def` for endpoints containing blocking code.

FastAPI automatically executes synchronous endpoints in a thread pool.

```python
@app.get("/users")
def get_users():
    time.sleep(2)
    return {"status": "ok"}
```

---

## Rule 2: Prefer Async-Compatible Libraries

When using `async def`, every I/O operation should also be asynchronous.

### Recommended Replacements

| Blocking Library | Async Alternative     |
| ---------------- | --------------------- |
| `time.sleep()`   | `asyncio.sleep()`     |
| `requests`       | `httpx.AsyncClient()` |
| `pymongo`        | `motor`               |
| `psycopg2`       | `asyncpg`             |
| SQLAlchemy Sync  | SQLAlchemy Async      |

Example:

```python
import asyncio
import httpx

@app.get("/external")
async def fetch_data():
    await asyncio.sleep(1)

    async with httpx.AsyncClient() as client:
        response = await client.get("https://example.com")

    return response.json()
```

---

## Rule 3: Offload Heavy Computation

FastAPI excels at I/O-bound workloads, not CPU-bound workloads.

### Lightweight Tasks (<100 ms)

Can run directly inside endpoints under low traffic.

### Heavy ML Inference

Use dedicated inference servers:

* Triton Inference Server
* TensorFlow Serving
* TorchServe

FastAPI should focus on:

* Request handling
* Validation
* Routing

### Long-Running Tasks

Use a queue-based architecture:

```text
FastAPI
    ↓
RabbitMQ / Redis
    ↓
Celery Workers
```

Examples:

* Video processing
* Image manipulation
* Batch jobs
* Report generation

---

## Rule 4: Apply the Same Rules to Dependencies

Dependencies should follow the same concurrency rules.

### Use `def` When

* Calling blocking libraries
* Using synchronous database drivers

### Use `async def` When

* Using async libraries
* Performing lightweight work

### Avoid

* Heavy computations inside dependencies

---

# 2. Background Processing & Task Orchestration

## Rule 5: Use Background Tasks for Lightweight Work

FastAPI's `BackgroundTasks` is ideal for fire-and-forget operations.

Examples:

* Sending emails
* Analytics logging
* Notifications

```python
from fastapi import BackgroundTasks

@app.post("/register")
async def register(background_tasks: BackgroundTasks):

    background_tasks.add_task(send_email)

    return {"message": "User created"}
```

### Limitations

Do **not** use `BackgroundTasks` when you need:

* Guaranteed delivery
* Retries
* Persistence across crashes

For mission-critical tasks, use:

* Celery
* RabbitMQ
* Redis

---

# 3. Security, Hardening & API Edge Controls

## Rule 6: Disable API Documentation in Production

### Anti-Pattern

Leaving these publicly exposed:

* `/docs`
* `/redoc`
* `/openapi.json`

This reveals:

* Internal schemas
* Endpoint structures
* Experimental APIs

### Production Practice

```python
from fastapi import FastAPI
from core.config import settings

app = FastAPI(
    docs_url=None if settings.ENVIRONMENT == "production" else "/docs",
    redoc_url=None if settings.ENVIRONMENT == "production" else "/redoc",
    openapi_url=None if settings.ENVIRONMENT == "production" else "/openapi.json",
)
```

---

# 4. Pydantic Architecture & Validation

## Rule 7: Create a Custom Base Model

Avoid inheriting directly from `BaseModel` everywhere.

Create a centralized application base model.

### Benefits

* Global configuration
* Alias generators
* Shared encoders
* Consistent serialization

Example:

```python
from pydantic import BaseModel

class AppBaseModel(BaseModel):

    class Config:
        populate_by_name = True
```

Common use cases:

* Snake case → camel case conversion
* `datetime` serialization
* `Decimal` conversion
* MongoDB `ObjectId` conversion

---

## Rule 8: Let FastAPI Build Response Models

### Anti-Pattern

```python
return UserResponse(
    id=user.id,
    name=user.name
)
```

### Production Practice

Return raw objects:

```python
return {
    "id": user.id,
    "name": user.name
}
```

FastAPI automatically:

1. Validates
2. Serializes
3. Builds the response model

---

## Rule 9: Keep Validation Inside Pydantic

### Anti-Pattern

```python
if age < 18:
    raise Exception()
```

inside route handlers.

### Production Practice

Use validators:

```python
from pydantic import BaseModel, field_validator

class UserCreate(BaseModel):

    age: int

    @field_validator("age")
    @classmethod
    def validate_age(cls, value):

        if value < 18:
            raise ValueError("Age must be at least 18")

        return value
```

Benefits:

* Cleaner routes
* Better OpenAPI docs
* Reusable validation logic

---

# 5. Dependency Injection & Resource Management

## Rule 10: Move Resource Validation Into Dependencies

Examples:

* Ownership checks
* Permission checks
* Record existence validation

Benefits:

* Reusability
* Cleaner endpoints
* Automatic request-level caching

```python
@app.get("/items/{id}")
async def get_item(
    item=Depends(get_existing_item)
):
    return item
```

---

## Rule 11: Use Connection Pools Through Dependency Injection

### Anti-Pattern

Creating a database client for every request.

### Production Practice

Initialize pools once during startup.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request

@asynccontextmanager
async def lifespan(app: FastAPI):

    app.state.db_pool = await create_db_pool()

    yield

    await app.state.db_pool.close()


app = FastAPI(lifespan=lifespan)


async def get_db(request: Request):

    async with request.app.state.db_pool.acquire() as connection:
        yield connection
```

---

## Rule 12: Manage Global State with Lifespan

Avoid:

```python
@app.on_event("startup")
@app.on_event("shutdown")
```

Prefer:

```python
lifespan()
```

Use it for:

* Database pools
* Redis connections
* Kafka consumers
* Cache systems
* Background services

Benefits:

* Centralized initialization
* Better error handling
* Cleaner shutdown

---

# 6. Secure Configuration & Observability

## Rule 13: Centralize Configuration with Pydantic Settings

### Avoid

```python
os.environ["DATABASE_URL"]
```

scattered throughout the project.

### Production Practice

Use:

* `.env`
* `.env.example`
* `pydantic-settings`

Example:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):

    DATABASE_URL: str
    ENVIRONMENT: str

    class Config:
        env_file = ".env"


settings = Settings()
```

Benefits:

* Startup validation
* Fail fast on missing values
* Type safety

---

## Rule 14: Use Structured JSON Logging

### Avoid

```python
print("User logged in")
```

### Production Practice

Use:

* `logging`
* `structlog`
* `loguru`

Example:

```python
logger.info(
    "user_login",
    user_id=user.id,
    request_id=request_id
)
```

### Include Context

* request_id
* user_id
* trace_id

### Send Logs To

* Fluent Bit
* Logstash
* Elasticsearch

Benefits:

* Better observability
* Easier debugging
* Distributed tracing support

---

# 7. High-Performance Deployment

## Rule 15: Run Uvicorn Behind Gunicorn

Use:

```bash
gunicorn app.main:app -k uvicorn.workers.UvicornWorker --workers 5
```

### Why

Gunicorn provides:

* Process management
* Worker supervision
* Better production stability

Uvicorn provides:

* ASGI support
* High-performance networking

### Enable `uvloop`

FastAPI automatically benefits from `uvloop` for improved throughput.

### Worker Formula

```text
workers = (CPU_CORES × 2) + 1
```

Always benchmark before finalizing worker counts.

---

# Summary

### Concurrency

* Avoid blocking inside `async def`
* Use async libraries
* Offload CPU-heavy work

### Background Tasks

* Use native tasks only for lightweight operations
* Use Celery for reliability

### Security

* Disable docs in production

### Pydantic

* Create a custom base model
* Keep validation inside schemas

### Dependencies

* Reuse validation logic
* Use connection pools

### Configuration

* Centralize settings
* Validate at startup

### Observability

* Structured JSON logs
* Trace request context

### Deployment

* Gunicorn + Uvicorn
* Enable `uvloop`
* Benchmark worker counts


# 2.5 High-Performance Data Access & Task Management

Production-grade FastAPI applications must provide low-latency responses while handling resource-intensive workloads efficiently. Achieving this requires a two-pronged strategy:

- **Caching** to reduce database latency.
- **Task orchestration** to execute long-running operations asynchronously.

---

# Rule 16: Implement Redis for Caching Frequently Accessed Data

Database I/O is often the largest performance bottleneck in web applications. Use **Redis** to cache expensive database queries or computationally intensive results.

## The Caching Pattern

```python
from redis import asyncio as aioredis
import json

# Setup Redis in your lifespan or as a dependency
async def get_cached_user(user_id: int):
    redis = await get_redis_client()

    cached_data = await redis.get(f"user:{user_id}")

    if cached_data:
        return json.loads(cached_data)

    # Cache miss: Fetch from database
    user = await db.fetch_user(user_id)

    # Cache the result with a TTL
    await redis.setex(
        f"user:{user_id}",
        3600,
        json.dumps(user)
    )

    return user
```

---

## Redis Caching Best Practices

### 1. Always Set a TTL (Time-To-Live)

Every cached object should expire automatically to prevent stale data.

```python
await redis.setex(
    "user:42",
    3600,  # 1 hour
    json.dumps(user)
)
```

Benefits:

- Prevents stale cache
- Reduces memory usage
- Enables automatic cache cleanup

---

### 2. Implement Cache Invalidation

Whenever data changes, invalidate the corresponding cache entry.

```python
await db.update_user(user_id, payload)

await redis.delete(f"user:{user_id}")
```

Remember:

> **Cache invalidation is one of the hardest problems in computer science.**

Always ensure cached objects reflect the current database state.

---

### 3. Redis Is Not Your Primary Database

Redis should only store:

- Frequently accessed data
- Expensive database queries
- Computationally expensive results
- Session information
- Rate limiting metadata

Your **primary relational database** (PostgreSQL, MySQL, etc.) should always remain the source of truth.

---

## Typical Redis Use Cases

| Use Case | Good Candidate? |
|-----------|-----------------|
| User Profiles | ✅ |
| Product Catalog | ✅ |
| Feature Flags | ✅ |
| Session Storage | ✅ |
| Authentication Tokens | ✅ |
| Dashboard Statistics | ✅ |
| Large Binary Files | ❌ |
| Permanent Business Data | ❌ |

---
# Rule 17: ## 8: Automating Quality Control with `lint.sh` and `fix.sh`

To maintain a production-grade codebase, integrate linting and formatting into your development lifecycle. Use these scripts to enforce standards consistently across your team.

### `fix.sh` (Auto-Correction)
Use this script to automatically clean up code style issues and format files according to project standards.

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "Auto-fixing code..."
uv run ruff check . --fix
uv run ruff format .
echo "Formatting completed."
---
# Rule 18: Utilize Celery for Long-Running & Blocking Tasks

Although FastAPI excels at handling asynchronous I/O, it is **not designed for CPU-intensive or long-running background jobs**.

Delegate such work to **Celery workers**, backed by a message broker such as:

- Redis
- RabbitMQ

---

## When to Use Celery

Use Celery whenever a task:

### Time-Consuming

Examples:

- PDF generation
- Excel report generation
- Video transcoding
- AI inference
- Image processing

---

### Depends on Slow External APIs

Examples:

- Email sending
- SMS notifications
- Payment webhooks
- Third-party integrations
- Batch API synchronization

---

### Requires Reliability

If a task:

- Must eventually succeed
- Needs retries
- Should survive server restarts
- Can be processed later

then Celery is the appropriate solution.

---

# Integration Strategy

Keep task definitions separate from your API layer.

```
app/
├── api/
├── services/
├── repositories/
├── tasks/
│   ├── worker.py
│   ├── report_tasks.py
│   ├── email_tasks.py
│   └── notification_tasks.py
```

This separation improves maintainability and keeps business logic decoupled from HTTP request handling.

---

## Example Celery Worker

```python
# app/tasks/worker.py

from celery import Celery

celery_app = Celery(
    "worker",
    broker="redis://localhost:6379/0"
)

@celery_app.task(bind=True, max_retries=3)
def process_heavy_report(self, report_id: int):
    try:
        # Complex business logic
        ...
    except Exception as exc:
        raise self.retry(
            exc=exc,
            countdown=60
        )
```

---

# Production Workflow

## Step 1 — Dispatch the Task

Instead of executing heavy work inside the request, enqueue it.

```python
@router.post("/reports/{report_id}")
async def generate_report(report_id: int):
    process_heavy_report.delay(report_id)

    return {
        "message": "Report generation started."
    }
```

The HTTP response is returned immediately while Celery processes the task asynchronously.

---

## Step 2 — Monitor Workers

Use monitoring tools such as:

- Flower
- Prometheus
- Grafana

Monitor:

- Worker health
- Queue depth
- Running tasks
- Failed tasks
- Retry counts

---

## Step 3 — Isolate Worker Infrastructure

Deploy Celery workers separately from the FastAPI application.

Example Docker architecture:

```
                ┌──────────────┐
                │   FastAPI    │
                └──────┬───────┘
                       │
             Dispatch Task
                       │
                ┌──────▼───────┐
                │ Redis Queue  │
                └──────┬────────┘
                       │
         ┌─────────────┴─────────────┐
         │                           │
┌────────▼────────┐        ┌──────────▼─────────┐
│ Celery Worker 1 │        │ Celery Worker 2    │
└─────────────────┘        └────────────────────┘
```

This architecture prevents heavy workloads from consuming resources needed by the API server.

---

# BackgroundTasks vs Celery

| Feature | FastAPI BackgroundTasks | Celery |
|----------|-------------------------|--------|
| Persistence | In-memory (lost on crash) | Persistent (Redis/RabbitMQ) |
| Retries | ❌ Not supported | ✅ Native retry support |
| Exponential Backoff | ❌ | ✅ |
| Scheduling (Cron Jobs) | ❌ | ✅ |
| Worker Scaling | Tied to API instance | Independent workers |
| Monitoring | Minimal | Flower, Prometheus, Grafana |
| Complexity | Very Low | Moderate |
| Reliability | Low | High |
| Best For | Small background work | Production-grade asynchronous processing |

---

# Choosing the Right Tool

## Use FastAPI `BackgroundTasks` When

- Writing logs
- Sending quick notifications
- Cleaning temporary files
- Lightweight cache updates
- Tasks lasting only a few seconds

---

## Use Celery When

- Processing reports
- Running AI/ML inference
- Sending bulk emails
- Importing/exporting datasets
- Video or image processing
- Scheduled jobs
- Tasks requiring retries
- Mission-critical background workflows

---

# Key Takeaways

- Use **Redis** to minimize database latency by caching frequently accessed or expensive-to-compute data.
- Always configure **TTL** values and implement **cache invalidation** to maintain data consistency.
- Treat Redis as a **cache**, not as the system of record.
- Offload CPU-intensive or long-running tasks to **Celery** to keep API responses fast.
- Deploy Celery workers independently from FastAPI to improve scalability and fault isolation.
- Use **FastAPI BackgroundTasks** only for lightweight, fire-and-forget operations.
- Choose **Celery** whenever reliability, retries, scheduling, or horizontal scaling are required.
```