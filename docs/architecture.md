# RepoLens architecture

## Document status

- **Current milestone:** Stage 5 — deterministic repository-quality findings
- **Last updated:** 2026-07-24
- **Architecture style:** monorepo with a modular-monolith backend and a separate web application

This document distinguishes the code that exists through Stage 5 from the target MVP architecture. A component described as planned must not be treated as implemented.

## Architectural goals

RepoLens should remain understandable to a junior developer while creating strong boundaries around untrusted repository content. The architecture is designed to provide:

- deterministic and explainable analysis;
- evidence for every finding and score impact;
- strict separation between repository acquisition, inspection, parsing, rules, scoring, and reporting;
- asynchronous processing for analysis that cannot complete within a normal HTTP request;
- temporary source retention with guaranteed cleanup;
- incremental delivery without premature microservices or shared packages.

## Current Stage 5 architecture

The current architecture keeps the web application independent and connects deterministic inventory, source parsing, and quality findings to the hardened acquisition worker with cleanup-before-finalization:

```mermaid
flowchart LR
    B["Browser"] --> W["Next.js landing page"]
    C["HTTP client"] -->|"Analysis lifecycle and result reads"| A["FastAPI application"]
    D["Docker Compose"] --> W
    D --> A
    A --> P["PostgreSQL"]
    A --> J["Typed result validation"]
    J --> P
    A --> R["Redis broker"]
    R --> K["Hardened Celery analysis worker"]
    K --> P
    K --> G["Public github.com repository"]
    K --> T["Bounded temporary workspace"]
    K --> E["Deterministic inventory modules"]
    E --> Q["Bounded source-structure modules"]
    Q --> F["Deterministic quality findings"]
    F --> S["Explicit deterministic serializer"]
    S -->|"Atomic result plus completed commit"| P
```

The Next.js page still has a repository URL field and disabled action button; it does not call the API. FastAPI exposes `GET /health`, the analysis lifecycle endpoints, and `GET /api/v1/analyses/{analysis_id}/result`. New completed analyses return typed schema version 3 inventory, `code_structure`, and `quality_findings` data. Existing schema version 1 rows remain readable with both newer fields set to null; version 2 rows retain typed structure and return `quality_findings: null`. Queued and processing analyses return `analysis_not_ready`; failed analyses return `analysis_failed`; completed analyses without a result return the integrity error `analysis_result_missing`.

The API accepts only canonicalizable public HTTPS GitHub repository URLs, stores repository identities and analysis lifecycle records, and publishes work to Redis. The worker shallow-clones only the stored canonical URL, yields the validated repository root through a bounded async context, runs inventory, supported-language structure analysis, and quality rules while that context exists, and removes the temporary source before opening the result finalization transaction. A successful finalization persists `AnalysisResult` and changes the owned analysis to `completed` in one commit. Legacy completed rows without a result still report `analysis_result_missing`.

Alembic owns the PostgreSQL schema. SQLAlchemy's asynchronous engine and sessions are shared by the API and worker. Redis is transport only and is not a system of record.

### Current repository boundaries

```text
apps/web     Next.js App Router UI, styles, and frontend tests
apps/api     FastAPI API, persistence, migrations, acquisition worker, and tests
docs         Requirements, roadmap, architecture, and ADRs
compose.yaml Local web, API, worker, PostgreSQL, and Redis orchestration
```

The applications manage their dependencies independently with pnpm and uv. There is no shared-contracts, shared-config, or analysis-core package because no implemented consumers require one.

### Implemented analysis lifecycle

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> processing: worker accepts job
    queued --> failed: dispatch or setup failure
    processing --> completed: inventory, structure, quality, cleanup, and result commit succeed
    processing --> failed: deterministic work or cleanup fails safely
    completed --> [*]
    failed --> [*]
```

Terminal jobs are idempotent when redelivered. The transition policy blocks all other state changes. Safe, generic failure messages are persisted and returned; internal exception details are not exposed through the API.

### Deterministic result persistence

`InventoryResult`, `CodeStructureResult`, and `QualityFindingsResult` remain in-memory immutable contracts. Explicit serialization selects only repository summary, language statistics, important-file signals, technology evidence, entry-point evidence, bounded declarations and imports, fixed finding metadata, numeric evidence, safe relative paths, counters, and fixed warnings. Enums become string values and tuples become JSON arrays. The serializer rejects inconsistent finding text or summary counters, unsupported Python objects, non-finite floats, and absolute or traversing paths, then measures canonical UTF-8 JSON using sorted keys, fixed separators, and disabled NaN support.

The `analysis_results` table stores at most one result per analysis:

```text
analysis_results
├── analysis_id       UUID primary key, foreign key to analyses.id, ON DELETE CASCADE
├── schema_version    positive integer
├── payload           PostgreSQL JSONB (generic JSON in isolated SQLite tests)
└── created_at        timezone-aware database timestamp
```

Persistence first serializes and enforces the 2 MiB default byte limit without holding a database row lock. Finalization then locks the owning analysis briefly and writes only when the analysis is still `processing` with the same processing token. The result insert or update and the transition to `completed` share one transaction and commit. A rollback leaves neither a partial result nor a completed state. Another token and every non-processing lifecycle state are no-ops.

## Target MVP architecture (planned)

The MVP will preserve the same deployable web and backend boundaries while adding asynchronous analysis inside the backend codebase:

```mermaid
flowchart LR
    U["User"] --> W["Next.js dashboard"]
    W --> A["FastAPI API"]
    A --> P["PostgreSQL"]
    A --> Q["Redis queue"]
    Q --> K["Celery worker"]
    K --> G["Public GitHub repository"]
    K --> T["Temporary workspace"]
    K --> E["Deterministic analysis modules"]
    E --> P
```

The API and worker will use modules from the same backend codebase and domain model. The worker is a separate process for operational reasons, not an independently owned microservice.

### Planned component responsibilities

| Component | Responsibility |
| --- | --- |
| URL policy | Accept and canonicalize only supported public `github.com/{owner}/{repository}` URLs. |
| Repository acquisition | Fetch a bounded snapshot into an isolated temporary workspace without executing it. |
| File inventory | Record safe paths, sizes, extensions, exclusions, and a bounded directory tree. |
| Technology detection | Identify languages and important configuration files from deterministic evidence. |
| Documentation inspection | Derive bounded README, documentation, governance, and onboarding signals without persisting document text. |
| Source parsing | Extract bounded Python AST and TypeScript/JavaScript Tree-sitter declarations, imports, exports, counters, and safe warnings without executing source. |
| Rule engine | Produce implemented findings whose code, category, severity, numeric evidence, safe paths, and recommendation are explicit. |
| Scoring | Calculate versioned, deterministic category scores and a bounded total score. |
| Reporting | Build one versioned report model used by the API, dashboard, JSON export, and Markdown export. |
| Job orchestration | Own analysis state transitions, idempotency, timeouts, failures, and cleanup. |

The backend may introduce internal modules as these responsibilities become real. The boundaries should be visible in code, but each milestone should add only the structure it uses.

## Data flow

Stages 1 through 5 implement steps 1-13 as one backend flow:

1. The user submits a public GitHub repository URL.
2. The API validates and canonicalizes the URL, then records an analysis request.
3. The API enqueues an idempotent background job and returns an analysis identifier.
4. The Celery worker atomically claims the analysis using its delivery identifier, reloads the canonical URL from PostgreSQL, and acquires a shallow repository snapshot in an isolated temporary directory.
5. Acquisition disables repository hooks, prompts, credential helpers, submodules, LFS smudging, unsafe protocols, and redirects; time and workspace growth are bounded throughout the Git process.
6. A security pass rejects limit violations, symbolic links, unsafe paths, and special files before inventory begins.
7. Inventory derives bounded metadata, language, manifest, technology, and conservative entry-point evidence without executing repository code.
8. The source-structure service consumes only supported safe inventory entries, uses Python AST or fixed TypeScript/JavaScript Tree-sitter grammars, and emits bounded declarations, imports, counters, and fixed warnings.
9. The quality service consumes only bounded inventory, manifest, entry-point, and structure facts. It reads selected README and CI files through the symlink-resistant content reader, accepts UTF-8 or UTF-8 BOM only, extracts counters and boolean signals, and discards the text.
10. Fixed rules emit positive and improvement findings across documentation, testing, governance, automation, maintainability, and onboarding. A monotonic deadline and finding, evidence, path, and document-read limits bound the pass.
11. The complete inventory, structure, and quality result remain in memory while the acquisition context removes Git metadata and the temporary workspace.
12. Only after cleanup succeeds, the explicit serializer produces a deterministic, size-limited schema version 3 payload without document text, CI commands, source bodies, snippets, parser diagnostics, or dependency values.
13. A short transaction verifies processing-token ownership, stores the single JSONB result, and marks the analysis completed atomically.
14. The typed result endpoint reads versions 1, 2, and 3. A deterministic fatal error records a safe failed state; a database finalization failure is raised for Celery redelivery.
15. Future scoring may consume these typed findings but is not implemented by Stage 5.
14. The future web dashboard will poll the API and render completed results.

## Data ownership and persistence

The current schema stores canonical repository identity, analysis lifecycle metadata, a safe analysis error code, an internal processing-delivery token, and at most one versioned deterministic result in `repositories`, `analyses`, and `analysis_results`. The full file inventory, syntax trees, README text, and CI text remain in memory; only bounded derived metadata, fixed finding text, numeric evidence, and safe relative paths can enter the explicit JSONB payload. Source files, document paragraphs, CI commands, snippets, docstrings, literals, parser exceptions, workspace paths, processing tokens, dependency values, script commands, Git output, and repository snapshots are not stored in analysis results.

Alembic migrations version the PostgreSQL schema. PostgreSQL is the system of record; Redis is used only for queue transport and transient coordination.

## Security invariants

The following rules apply now and to every future milestone:

1. RepoLens never executes code or scripts from an analyzed repository.
2. Repository content is untrusted data; dependency installation, hooks, builds, tests, binaries, and entry points are prohibited.
3. Acquisition must use an allowlisted GitHub URL policy and resist redirects and SSRF.
4. Repository, file-count, file-size, document-read, parser-time, finding-count, evidence, related-path, and total-analysis limits must be explicit and tested.
5. Symbolic links must not escape the temporary analysis root.
6. Source content is temporary and must be removed before success finalization and on every failure or cancellation path.
7. Logs and persistent records must not contain source bodies, credentials, or tokens.
8. AI may explain verified structured facts but must not invent files, technologies, or findings.

## Development and operational model

- `apps/web` runs as a Next.js development server on port 3000.
- `apps/api` runs as a FastAPI/Uvicorn development server on port 8000.
- Docker Compose runs PostgreSQL and Redis with health checks and starts the API and worker only after both dependencies are healthy.
- The worker runs as UID/GID 65534 with a read-only root filesystem, no Linux capabilities, no-new-privileges, explicit memory/CPU/PID limits, and bounded noexec tmpfs mounts for runtime and repository data.
- The API and worker reach PostgreSQL and Redis over separate internal networks. Only the worker joins its egress network; Docker Compose does not enforce a domain-based GitHub allowlist.
- PostgreSQL and Redis development ports bind only to host loopback. The worker source bind mount is limited to read-only application source.
- GitHub Actions independently verifies backend formatting, linting, typing, and tests, plus frontend linting, typing, tests, and production build.

Commands and local prerequisites are documented in the repository README. Architecture changes that alter component ownership, deployment boundaries, data retention, or safety guarantees require an ADR.

## Evolution constraints

Split a backend capability into a separate service only when measured scaling, reliability, release cadence, or ownership needs justify the operational cost. Introduce a shared package only after implemented consumers require a stable shared contract. Until then, favor explicit modules and ordinary function calls within the backend codebase.
