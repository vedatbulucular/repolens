# Contributing to RepoLens

Thank you for helping improve RepoLens. The project favors focused, well-tested contributions that stay within the current milestone and keep the architecture approachable for newer developers.

## Before you start

For a non-trivial change, open or join an issue first so the scope and acceptance criteria are clear. Review the following documents:

- [Product requirements](docs/product-requirements.md)
- [Architecture](docs/architecture.md)
- [Development roadmap](docs/development-roadmap.md)
- [Repository instructions](AGENTS.md)

The most important safety invariant is that RepoLens never executes code or scripts from an analyzed repository.

## Prerequisites

For native development, install:

- Node.js 22.12 or later
- pnpm 11.9.0 (the release pinned by the repository)
- Python 3.12 or later
- uv

Alternatively, install Docker Desktop or Docker Engine with Docker Compose v2.

## Local setup

Clone your fork, enter the repository, and create a local environment file:

```bash
git clone https://github.com/<your-account>/repolens.git
cd repolens
cp .env.example .env
```

On Windows PowerShell, use `Copy-Item .env.example .env` for the final command.

Install native dependencies from the repository root:

```bash
pnpm --dir apps/web install
uv --directory apps/api sync
```

Start the two applications in separate terminals:

```bash
pnpm --dir apps/web dev
```

```bash
uv --directory apps/api run uvicorn repolens_api.main:app --reload --app-dir src --host 0.0.0.0 --port 8000
```

The web app is served at `http://localhost:3000`; the API health check is at `http://localhost:8000/health`.

To use containers instead:

```bash
docker compose up --build
```

Stop the containers with `docker compose down`. PostgreSQL and Redis are present for future milestones and are not application dependencies in Stage 0.

## Branches

- Branch from the latest `main`.
- Use a short, descriptive, kebab-case name prefixed with the change type, such as `feat/analysis-status`, `fix/health-response`, `docs/local-setup`, or `chore/ci-cache`.
- Keep one logical change per branch. Do not mix unrelated formatting or refactoring into a feature change.
- Rebase or merge the current `main` as appropriate before requesting final review, and resolve conflicts deliberately.

## Commits

Use concise, imperative commit messages. Conventional Commit prefixes are encouraged:

```text
feat: add analysis status contract
fix: preserve health response version
test: cover invalid repository owner
docs: clarify native setup
```

- Make each commit buildable and reviewable when practical.
- Explain *why* in the commit body when the reason is not obvious from the change.
- Never commit secrets, local `.env` files, dependency caches, virtual environments, or build output.

## Tests and quality checks

Run every check affected by your change. For backend changes:

```bash
uv --directory apps/api run ruff format --check .
uv --directory apps/api run ruff check .
uv --directory apps/api run mypy
uv --directory apps/api run pytest
```

For frontend changes:

```bash
pnpm --dir apps/web lint
pnpm --dir apps/web type-check
pnpm --dir apps/web test
pnpm --dir apps/web build
```

For infrastructure changes:

```bash
docker compose config
```

Behavior changes require new or updated tests. Do not remove or weaken a valid failing test to obtain a green result. If a required check cannot run in your environment, state the command and reason in the pull request.

## Dependencies

Keep dependencies minimal. A pull request that adds or replaces a dependency must explain:

- the problem it solves;
- why existing dependencies or the standard library are insufficient;
- relevant runtime, maintenance, licensing, and security implications.

Update the appropriate lockfile in the same change.

## Pull requests

Before opening a pull request:

1. Confirm the change is within the active milestone and linked issue scope.
2. Add or update tests for changed behavior.
3. Run all affected checks and record the results.
4. Update documentation and `.env.example` when behavior, commands, architecture, or configuration changes.
5. Review the diff for secrets, debug output, generated files, and unrelated edits.

In the pull request description, include:

- a concise problem and solution summary;
- the important design choices and trade-offs;
- each verification command and its result;
- screenshots for visible interface changes;
- any known limitation or follow-up work;
- the purpose of each new dependency.

Keep pull requests small enough to review carefully. Temporary workarounds must document their limitation and removal condition.
