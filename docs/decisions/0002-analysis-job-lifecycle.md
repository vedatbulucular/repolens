# ADR 0002: Persist and queue the analysis job lifecycle

- **Status:** Accepted
- **Date:** 2026-07-21

## Context

Stage 1 needs a durable repository identity, observable asynchronous job states, and a queue boundary without beginning repository acquisition or analysis. The existing modular-monolith decision keeps API and worker code in one backend codebase while allowing them to run as separate processes.

The lifecycle must be explicit, testable, safe under task redelivery, and independent of any GitHub network request. API errors must remain machine-readable without exposing database, broker, or exception internals.

## Decision

### Process analyses asynchronously

Analysis work will outlive a normal HTTP request once bounded acquisition and deterministic inspection are implemented. The API therefore persists a job and returns `202 Accepted`, while a separate worker owns its execution. This keeps request latency bounded and creates a future control point for concurrency, retries, timeouts, cancellation, and cleanup.

Stage 1 uses deterministic mock work only. It contacts no repository host and immediately exercises the persisted lifecycle.

### Use Celery with Redis

Celery provides a mature Python worker and task-delivery model that fits the FastAPI backend without adding a new language or service codebase. Redis is already part of the local infrastructure and is used only as the Celery broker; task results, repository source, and product records are not stored there.

PostgreSQL remains the system of record. SQLAlchemy 2 asynchronous sessions are used by both API and worker code, and Alembic owns all schema changes.

### Separate repositories from analyses

`repositories` stores one canonical identity per supported GitHub URL. `analyses` stores individual requests and their timestamps, status, and safe failure message. The one-to-many relationship avoids duplicating repository identity while preserving a history of separate analysis attempts.

The foreign key uses `ON DELETE CASCADE`, so deleting a repository identity cannot leave orphaned analysis records. Stage 1 exposes no repository deletion endpoint; this rule protects maintenance and rollback operations that deliberately remove an identity.

### Guard state transitions centrally

Analysis states are `queued`, `processing`, `completed`, and `failed`. One domain function allowlists transitions and owns timestamp and error-field updates. Terminal states cannot transition further, and redelivery of a terminal mock job is a no-op. Database enum constraints and unit tests reinforce the application policy.

API problem responses use stable machine-readable types and generic details. Internal exception text is not included.

## Consequences

- API requests require PostgreSQL and successful submissions require Redis; the health endpoint remains process-local.
- Local and container startup requires applying Alembic migrations before using analysis endpoints.
- The worker can be scaled as a separate process without creating a separate service codebase.
- Repository acquisition, retry policy, timeouts, cleanup, and analysis outputs remain explicitly deferred to later decisions and milestones.
- SQLite may be used only as an isolated test adapter for service and API behavior; PostgreSQL migration behavior is validated separately.
