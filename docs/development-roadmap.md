# RepoLens development roadmap

## Delivery model

RepoLens is delivered in small, reviewable stages. A stage may begin only after the preceding stage meets its acceptance criteria and the next scope is explicitly approved. Future-stage structure should not be added early unless the active stage uses it.

The invariant across all stages is that RepoLens never executes code or scripts from an analyzed repository.

## Stage 0 — Architecture decisions and project foundation

**Status:** Complete

### Scope

- Create the `apps/web` Next.js, TypeScript, Tailwind CSS, pnpm application.
- Create the `apps/api` FastAPI, Python, uv application with `GET /health`.
- Add a non-functional landing page and baseline frontend test.
- Add typed API settings, OpenAPI metadata, and a health endpoint test.
- Configure ESLint, TypeScript, Vitest, Ruff, mypy, and pytest.
- Define web, API, PostgreSQL, and Redis development services in Docker Compose.
- Add push and pull-request CI for all quality checks and the web production build.
- Add repository, architecture, product, roadmap, contribution, agent, and license documentation.

### Explicit boundary

No repository analysis, acquisition, URL validation, persistence models, migrations, Celery jobs, Tree-sitter, authentication, AI integration, scoring, or real dashboard behavior.

### Acceptance criteria

- The web and API development servers start with the documented native commands.
- The four-service Compose definition is valid and the web and API are reachable.
- `GET /health` returns the documented typed payload.
- Backend format, lint, type-check, and test checks pass.
- Frontend lint, type-check, test, and production-build checks pass.
- CI runs the same checks for pushes and pull requests.
- Documentation accurately states that analysis is not implemented.

## Stage 1 — Analysis lifecycle

**Status:** Complete

### Scope

- Define the supported public GitHub URL policy and canonicalization rules.
- Add the first repository and analysis persistence models with migrations.
- Add endpoints to create an analysis and read its state.
- Introduce Redis and Celery with an initial idempotent analysis job.
- Define and test queued, processing, completed, and failed transitions.

### Acceptance criteria

- A valid supported URL creates or reuses a canonical repository identity and returns an analysis ID.
- Unsupported or malformed URLs return a documented validation error.
- The worker moves an analysis through valid states and records safe failures.
- Migrations create and roll back the first schema in a clean database.
- No repository is downloaded or analyzed yet.

## Stage 2 — Safe repository acquisition

**Status:** Complete

### Scope

- Acquire public repository snapshots using the approved shallow-clone or archive strategy.
- Create isolated temporary workspaces with guaranteed cleanup.
- Enforce repository-size, file-count, file-size, redirect, and timeout limits.
- Prevent symbolic-link and path traversal outside the workspace.
- Classify acquisition failures without leaking source or credentials.

Stage 2A uses a depth-one, single-branch Git clone and rejects all symbolic links. Stage 2B confines the worker with a read-only root filesystem, dropped capabilities, no-new-privileges, bounded writable tmpfs mounts, explicit memory/CPU/PID limits, isolated data and egress networks, loopback-only infrastructure ports, and bounded Redis redelivery visibility. The source tree is scanned only to enforce safety limits; inventory and technology detection remain in Stage 3.

### Acceptance criteria

- Only repositories allowed by the public GitHub policy are acquired.
- Limit violations end in a documented safe failure state.
- Tests prove cleanup after success, failure, cancellation, and timeout.
- No repository-provided command, hook, dependency, or executable runs.
- The Docker worker is non-root, capability-free, read-only outside its bounded tmpfs mounts, and resource-limited.
- Worker loss preserves idempotent redelivery, while normal shutdown gives active acquisition time to clean up.

## Stage 3 — File inventory and technology detection

**Status:** Stage 3A-1 is complete on `main`; Stage 3A-2A is in development on `feature/repository-technology-detection`; the complete Stage 3A milestone is not yet implemented

### Scope

- Build a bounded file tree and metadata inventory.
- Detect languages from supported extensions and byte counts.
- Identify configuration, documentation, environment-example, CI, and test signals.
- Apply explicit directory, generated-content, binary, and oversized-file exclusions.
- Parse allowlisted manifest facts without retaining versions, commands, URLs, or source content.
- Detect bounded technology evidence and conservative entry points without ASTs.

### Acceptance criteria

- Fixed repository fixtures produce exact expected file, language, and byte totals.
- Important documentation and configuration signals are reported with source paths.
- Excluded, binary, oversized, and unsafe paths are skipped consistently.
- Inventory work remains within configured resource limits.

## Stage 4 — Python and TypeScript source parsing

### Scope

- Introduce pinned Tree-sitter support for Python and TypeScript.
- Extract basic classes, functions, methods, imports, and export signals.
- Add conservative entry-point heuristics.
- Isolate malformed-file and parser failures.

### Acceptance criteria

- Known Python and TypeScript fixtures produce the expected symbols and imports.
- Entry points always include a reason and evidence path.
- An invalid or unsupported source file does not fail the complete analysis.
- Parser time and file-size limits are enforced and tested.

## Stage 5 — Rule engine and deterministic scoring

### Scope

- Define a stable rule, finding, evidence, and score-impact contract.
- Add documentation, project-readiness, code-organization, and maintainability rules.
- Add versioned category weights and bounded score calculation.
- Document rule behavior and scoring rationale.

### Acceptance criteria

- Every finding has a stable rule ID and concrete machine-readable evidence.
- The same fixture and scoring version produce exactly the same findings and scores.
- Category and total scores stay within documented bounds.
- Rule caps prevent repeated signals from dominating a category unexpectedly.
- Unit tests cover positive, negative, boundary, and conflicting-rule cases.

## Stage 6 — Reporting and API completion

### Scope

- Define the versioned final report schema.
- Persist derived findings, scores, summaries, and exports.
- Add completed-result and error endpoints.
- Generate equivalent JSON and Markdown reports.
- Complete API and OpenAPI documentation for the analysis flow.

### Acceptance criteria

- API responses validate against the documented report schema.
- Stored reports include schema and scoring versions plus analyzed snapshot identity.
- JSON and Markdown exports represent the same core facts, findings, and scores.
- Source bodies and repository snapshots are absent from persistent records.

## Stage 7 — Analysis dashboard

### Scope

- Enable repository URL submission and actionable validation feedback.
- Display queued, running, completed, and failed states.
- Render score cards, repository structure, technologies, findings, evidence, and priorities.
- Add JSON and Markdown download actions.
- Cover keyboard access, responsive layout, empty states, and error recovery.

### Acceptance criteria

- A user can submit a supported URL and follow the analysis to a final state.
- A completed report exposes the reason and evidence behind each finding and score impact.
- Export links download the report generated by the API.
- Automated UI tests cover success, validation, progress, failure, and retry behavior.
- Core flows meet the documented accessibility expectations.

## Stage 8 — Quality, delivery, and open-source readiness

### Scope

- Add Playwright end-to-end coverage for the deployed user flow.
- Strengthen CI quality gates, dependency updates, and security checks.
- Document deployment, operations, limits, retention, backup, and failure recovery.
- Review public contribution, security, license, and architecture documentation.
- Validate a clean setup through native and Docker Compose workflows.

### Acceptance criteria

- End-to-end tests cover submission through report export.
- Required CI checks pass from a clean checkout and protect the main branch.
- A contributor can follow the documentation without undocumented setup steps.
- Operational documentation identifies limits, health signals, cleanup behavior, and recovery procedures.
- A release candidate passes the security invariant review: analyzed repository code is never executed.

## Deferred work

Private repository access, OAuth, account and team features, pull request or history analysis, automatic issue creation, advanced security scanning, additional deep-language parsers, AI chat, long-term source retention, and billing remain outside the MVP roadmap. They require separately approved requirements and architecture decisions.
