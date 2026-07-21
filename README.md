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

RepoLens is currently at **Stage 2A: safe repository acquisition**. The repository contains the Stage 0 foundation, the Stage 1 analysis lifecycle, and a Celery worker that acquires a bounded shallow snapshot of a stored canonical public GitHub repository URL in a temporary workspace.

Repository content analysis is **not implemented yet**. The worker does not build an inventory, detect technologies, parse files, score a project, or invoke AI. It never runs repository hooks, scripts, dependencies, tests, builds, or entry points. The acquired source and Git metadata are removed before the task records completion. The landing-page URL field and **Analyze Repository** button remain intentionally non-functional.

## Technology stack

| Area | Technology |
| --- | --- |
| Web | Next.js, React, TypeScript, Tailwind CSS |
| Web quality | ESLint, TypeScript, Vitest, Testing Library |
| API | FastAPI, Python, Pydantic Settings, SQLAlchemy, Alembic |
| API quality | Ruff, mypy, pytest |
| Package management | pnpm for the web app, uv for the API |
| Persistence and jobs | PostgreSQL, Redis, and Celery |
| Local infrastructure | Docker Compose |
| Continuous integration | GitHub Actions |

Tree-sitter, repository acquisition, deterministic repository inspection, scoring, and AI explanations remain planned; they are not part of the current implementation.

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
|-- compose.yaml                # Web, API, worker, PostgreSQL, and Redis services
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

PostgreSQL, Redis, Git, and trusted CA certificates are required for the native API worker. The Docker worker image includes Git and CA certificates; the API image does not add Git. The web landing page can still run independently.

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

Build the images and start the infrastructure from the repository root:

```bash
docker compose build
docker compose up -d postgres redis
```

Apply the database migration before starting the API and worker:

```bash
docker compose run --rm api alembic upgrade head
```

Migrations are not applied automatically. Run this command after a fresh setup and whenever the checked-in migration revision changes.

Start all services:

```bash
docker compose up
```

The web application is available at `http://localhost:3000`. The API health endpoint is available at `http://localhost:8000/health`, and interactive API documentation is available at `http://localhost:8000/docs`. The worker has no public port.

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

Start PostgreSQL and Redis, then migrate the local database:

```bash
docker compose up -d postgres redis
uv --directory apps/api run alembic upgrade head
```

Start the web development server:

```bash
pnpm dev:web
```

In another terminal, start the API development server:

```bash
pnpm dev:api
```

In another terminal, start the Celery worker. Native workers use an operating-system temporary directory by default; set an absolute `REPOLENS_API_WORKSPACE_ROOT` when an explicit location is required:

```bash
uv --directory apps/api run celery --app repolens_api.celery_app:celery_app worker --loglevel info
```

## Analysis lifecycle API

Create a queued analysis for a supported public GitHub URL:

```bash
curl -X POST http://localhost:8000/api/v1/analyses \
  -H "Content-Type: application/json" \
  -d '{"repository_url":"https://github.com/openai/openai-python.git"}'
```

Read its current state, including a safe `error_code` when acquisition fails, using the returned identifier:

```bash
curl http://localhost:8000/api/v1/analyses/ANALYSIS_ID
```

Only exact `https://github.com/{owner}/{repository}` URLs are accepted, with an optional trailing slash or `.git` suffix. Query strings, fragments, credentials, ports, extra path segments, SSH syntax, IP addresses, localhost, non-HTTPS schemes, and other hosts are rejected. Accepted values are stored as `https://github.com/{owner}/{repository}`.

API errors use `application/problem+json`. A malformed analysis UUID returns `422` with type `invalid_request`; a well-formed UUID with no corresponding record returns `404` with type `analysis_not_found`.

The worker uses only the canonical URL loaded from PostgreSQL. It performs a depth-one, single-branch, tags-free HTTPS clone with prompts, credential helpers, submodule recursion, LFS smudging, repository hooks, unsafe protocols, and HTTP redirects disabled. Source is validated only against the configured security limits; no file inventory is produced or stored.

The default acquisition limits are 60 seconds, 100 MiB of checked-out regular files, 256 MiB for the complete temporary workspace, 20,000 filesystem entries, 5 MiB per file, a 512-character relative path, and a maximum path depth of 40. The Docker worker stores workspaces in a 640 MiB tmpfs at `/tmp/repolens-workspaces`. Configure the corresponding `REPOLENS_API_*` variables documented in `.env.example` to change these bounds.

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

1. **Stage 0 — Foundation (complete):** monorepo scaffold, health endpoint, landing page, tests, Compose, CI, and documentation.
2. **Stage 1 — Analysis lifecycle (complete):** canonical public GitHub URLs, analysis records, status API, and queued jobs.
3. **Stage 2 — Safe acquisition (Stage 2A current):** bounded shallow clone, temporary workspaces, safe failures, and guaranteed cleanup. Additional container hardening remains for Stage 2B.
4. **Stage 3 — Inventory and detection:** file inventory, language detection, documentation signals, and exclusions.
5. **Stage 4 — Source parsing:** fault-tolerant Python and TypeScript symbol extraction with Tree-sitter.
6. **Stage 5 — Rules and scoring:** evidence-backed findings and versioned deterministic scores.
7. **Stage 6 — Reporting API:** versioned report contracts plus JSON and Markdown exports.
8. **Stage 7 — Dashboard:** analysis submission, progress, results, findings, and exports.
9. **Stage 8 — Release readiness:** end-to-end tests, quality gates, deployment guidance, and open-source hardening.

See the [development roadmap](docs/development-roadmap.md) for milestone boundaries and acceptance criteria.

## Security principle

**RepoLens must never execute code or scripts from an analyzed repository.** Untrusted repositories are treated as data only: no dependency installation, build command, test command, hook, or application entry point may be run. Stage 2A enforces explicit acquisition limits, rejects all symbolic links, stores source only temporarily, and removes it before the task reaches a terminal state.

## Contributing

Contributions are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a pull request. Keep changes within the active milestone, include tests for behavior changes, and explain the purpose of any new dependency.

## License

RepoLens is available under the [MIT License](LICENSE).
