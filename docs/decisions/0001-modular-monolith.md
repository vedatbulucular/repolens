# ADR 0001: Use a modular monolith for the RepoLens backend

- **Status:** Accepted
- **Date:** 2026-07-20
- **Decision owners:** RepoLens contributors

## Context

RepoLens will eventually coordinate public GitHub repository acquisition, safe file inventory, language detection, syntax parsing, deterministic rule evaluation, scoring, reporting, and asynchronous job execution. These responsibilities need clear boundaries, but the initial team and product scope do not justify independently deployed domain services.

The project also has a separate Next.js user interface and a FastAPI backend. “Modular monolith” in this decision refers to the backend product domains: they share one codebase, one domain model, and initially one release unit. A future Celery worker may run as a separate process while importing the same backend modules; that operational process does not make each analysis responsibility a microservice.

Stage 0 currently contains only the shallow FastAPI application required for settings, OpenAPI metadata, and `GET /health`. The internal analysis modules described here will be introduced only when their milestones implement real behavior.

## Decision

RepoLens will use a monorepo with:

- a separate Next.js application under `apps/web`;
- one modular FastAPI backend codebase under `apps/api`;
- PostgreSQL as the planned system of record;
- Redis and Celery as the planned queue and worker mechanism;
- explicit internal backend boundaries for acquisition, inventory, detection, parsing, rules, scoring, reporting, and job orchestration.

Internal modules will communicate through ordinary typed Python interfaces and domain objects. Boundaries must be testable and should prevent infrastructure details from leaking into deterministic analysis logic. They do not require separate network APIs, repositories, deployment pipelines, or databases.

No empty `analysis-core`, `shared-contracts`, or shared-config package will be created in advance. Shared code becomes a package only after multiple implemented consumers demonstrate a stable need.

## Rationale

A modular monolith provides the most useful properties for the current product:

- Junior contributors can trace a request and analysis job through one backend codebase.
- Transactions, schema evolution, local development, and end-to-end testing remain straightforward.
- Domain responsibilities can still be isolated and unit-tested.
- The team avoids distributed tracing, network failure modes, duplicated contracts, service discovery, and multiple deployment pipelines before those costs solve a measured problem.
- A worker can scale separately from the API process while reusing the same tested analysis code.
- Well-defined internal boundaries preserve the option to extract a component later.

## Consequences

### Positive

- Lower operational and cognitive overhead than microservices.
- Faster local setup and simpler CI for early milestones.
- One place to enforce repository safety, report contracts, and scoring versions.
- Refactoring across early domain boundaries remains practical while requirements evolve.
- Asynchronous analysis can scale at the worker-process level without immediate service extraction.

### Negative

- A poorly maintained module boundary could allow analysis concerns to become coupled.
- API and worker releases remain coordinated while they share the backend package.
- A single backend dependency graph can grow as parsers and infrastructure are added.
- Independent scaling is limited to process types until a module is extracted.

These costs will be controlled with explicit module ownership, typed interfaces, dependency discipline, focused tests, and ADRs for consequential changes.

## Alternatives considered

### Microservices from the first release

Rejected because the product has no demonstrated independent team ownership, release cadence, or scaling requirement for each domain. The operational complexity would obscure the analysis model and slow review.

### A single undifferentiated backend module

Rejected because acquisition, untrusted file handling, deterministic rules, scoring, and reporting have distinct responsibilities and safety implications. Keeping them conceptually separate is necessary even within one deployable application.

### Pre-created shared packages

Rejected for Stage 0 because no implemented consumers exist. Premature packages create contracts and maintenance overhead before their correct boundaries are known.

## Reconsideration triggers

Revisit this decision if measured evidence shows one or more of the following:

- a component requires an independent deployment or release cadence;
- a workload needs isolation that worker-process scaling cannot provide;
- separate teams own components with stable network contracts;
- dependency or failure isolation cannot be maintained within the backend package;
- regulatory or security boundaries require separate execution environments.

Any extraction must preserve the invariant that analyzed repository code is never executed and must define ownership, contracts, retries, observability, data retention, and migration strategy in a new ADR.
