# RepoLens

RepoLens is an open-source, AI-assisted platform for analyzing public GitHub repositories and helping developers understand unfamiliar codebases. Its planned analysis engine combines deterministic rules, file inspection, syntax-tree parsing, measurable signals, and explainable scoring. AI may later explain verified results, but it will not be the source of facts about a repository.

## Purpose

RepoLens is intended to help students, junior developers, open-source maintainers, technical recruiters, and engineers joining an unfamiliar project answer practical onboarding questions:

- How is the repository organized?
- Which languages, frameworks, and entry points matter?
- Is the documentation and test setup sufficient?
- Which maintainability improvements should be prioritized?
- How was the repository health score calculated?

## Development status

RepoLens is currently at **Stage 0: architecture decisions and project foundation**. The repository contains a minimal Next.js landing page, a FastAPI health endpoint, local development containers, quality tooling, CI, and foundational documentation.

Repository analysis is **not implemented yet**. The URL field and **Analyze Repository** button are intentionally non-functional, and the API has no GitHub integration, persistence models, background jobs, authentication, or analysis engine. PostgreSQL and Redis are provisioned by Docker Compose for future milestones but are not used by the applications in Stage 0.

## Technology stack

| Area | Technology |
| --- | --- |
| Web | Next.js, React, TypeScript, Tailwind CSS |
| Web quality | ESLint, TypeScript, Vitest, Testing Library |
| API | FastAPI, Python, Pydantic Settings |
| API quality | Ruff, mypy, pytest |
| Package management | pnpm for the web app, uv for the API |
| Future persistence and jobs | PostgreSQL, Redis, and Celery |
| Local infrastructure | Docker Compose |
| Continuous integration | GitHub Actions |

Tree-sitter, Celery, database models, and repository acquisition are planned technologies; they are not part of the current implementation.

## Repository structure

```text
repolens/
|-- apps/
|   |-- api/                    # FastAPI service and backend tests
|   `-- web/                    # Next.js App Router application and tests
|-- docs/
|   |-- decisions/              # Architecture decision records
|   |-- architecture.md         # Current and planned system boundaries
|   |-- development-roadmap.md  # Stages 0-8 and acceptance criteria
|   `-- product-requirements.md # MVP scope and product constraints
|-- .github/workflows/          # Continuous integration
|-- .env.example                # Documented local defaults; no secrets
|-- compose.yaml                # Web, API, PostgreSQL, and Redis services
|-- AGENTS.md                   # Persistent repository instructions
|-- CONTRIBUTING.md             # Contribution workflow
`-- README.md
```

Shared packages are intentionally absent. They will be introduced only when two or more implemented components have a concrete need for the same code or contract.

## Requirements

Choose either Docker or the native toolchain.

For Docker-based development:

- Docker Desktop or Docker Engine with Docker Compose v2

For development without Docker:

- Node.js 22.12 or later
- pnpm 11.9.0 (the release pinned by the root `packageManager` field)
- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/)

PostgreSQL and Redis are not required when running the Stage 0 web and API applications directly because neither application connects to them yet.

## Run with Docker Compose

Create a local environment file from the documented example:

```bash
# macOS or Linux
cp .env.example .env
```

```powershell
# Windows PowerShell
Copy-Item .env.example .env
```

Build and start all services from the repository root:

```bash
docker compose up --build
```

The web application is available at `http://localhost:3000`. The API health endpoint is available at `http://localhost:8000/health`, and interactive API documentation is available at `http://localhost:8000/docs`.

Stop the environment with:

```bash
docker compose down
```

Add `--volumes` only when you deliberately want to delete local PostgreSQL and Redis development data.

## Run without Docker

Install dependencies from the repository root:

```bash
pnpm install --frozen-lockfile
uv --directory apps/api sync --locked --all-groups
```

Start the web development server:

```bash
pnpm dev:web
```

In another terminal, start the API development server:

```bash
pnpm dev:api
```

## Quality checks

Run all backend and frontend lint checks from the repository root:

```bash
pnpm lint
```

Run all backend and frontend type checks and tests, then build the web application:

```bash
pnpm type-check
pnpm test
pnpm build:web
```

Validate the Compose definition with:

```bash
docker compose config
```

## MVP roadmap

1. **Stage 0 — Foundation:** monorepo scaffold, health endpoint, landing page, tests, Compose, CI, and documentation.
2. **Stage 1 — Analysis lifecycle:** canonical public GitHub URLs, analysis records, status API, and queued mock jobs.
3. **Stage 2 — Safe acquisition:** bounded temporary repository acquisition with guaranteed cleanup.
4. **Stage 3 — Inventory and detection:** file inventory, language detection, documentation signals, and exclusions.
5. **Stage 4 — Source parsing:** fault-tolerant Python and TypeScript symbol extraction with Tree-sitter.
6. **Stage 5 — Rules and scoring:** evidence-backed findings and versioned deterministic scores.
7. **Stage 6 — Reporting API:** versioned report contracts plus JSON and Markdown exports.
8. **Stage 7 — Dashboard:** analysis submission, progress, results, findings, and exports.
9. **Stage 8 — Release readiness:** end-to-end tests, quality gates, deployment guidance, and open-source hardening.

See the [development roadmap](docs/development-roadmap.md) for milestone boundaries and acceptance criteria.

## Security principle

**RepoLens must never execute code or scripts from an analyzed repository.** Untrusted repositories are treated as data only: no dependency installation, build command, test command, hook, or application entry point may be run. Future acquisition and parsing work must also enforce explicit limits, avoid following unsafe links, store source only temporarily, and remove it after analysis.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Keep changes within the active milestone, include tests for behavior changes, and explain the purpose of any new dependency.

## License

RepoLens is available under the [MIT License](LICENSE).
