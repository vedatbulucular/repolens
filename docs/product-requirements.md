# RepoLens product requirements

## Product vision

RepoLens is an open-source web application that helps people understand and improve public GitHub repositories. It will turn repository structure and source metadata into an onboarding-oriented report containing concrete evidence, explainable health scores, and prioritized recommendations.

RepoLens is not a wrapper that sends an entire codebase to an AI model. Deterministic analysis is the source of truth. AI-assisted explanations may be added later only on top of verified structured results.

## Current delivery scope

Stage 2 adds bounded, temporary repository acquisition to the durable Stage 1 lifecycle. It accepts and canonicalizes supported public GitHub repository URLs, persists repository identity and job state, and lets the worker shallow-clone only the stored canonical URL under strict process, filesystem, and container controls.

Stage 2 contacts GitHub only through a hardened HTTPS Git clone. The Docker worker is non-root, has a read-only root filesystem, no Linux capabilities, no-new-privileges, bounded writable tmpfs mounts, explicit resource limits, and separated data and egress networks. It does not inventory source, detect technologies, parse files, score projects, persist source, or invoke AI. The web repository URL field and action button remain intentionally non-functional; only the backend lifecycle and acquisition flow are implemented.

## Target users

- Students and junior developers seeking feedback on portfolio repositories
- Developers onboarding to an unfamiliar codebase
- Open-source maintainers improving contributor readiness
- Technical recruiters reviewing public portfolio projects
- Engineering teams evaluating the structure and documentation of public projects

## Product principles

1. **Evidence before interpretation:** every finding identifies its rule and machine-readable evidence.
2. **Deterministic scoring:** the same supported repository snapshot and scoring version produce the same result.
3. **Safe inspection:** analyzed repositories are untrusted data and are never executed.
4. **Explainable output:** users can understand why a category gained or lost points.
5. **Onboarding focus:** the report helps a developer find entry points, setup guidance, tests, and improvement priorities.
6. **Bounded AI assistance:** AI may summarize verified results but may not invent facts or act as the analysis engine.
7. **Incremental architecture:** implement real requirements without premature services or shared packages.

## MVP functional requirements

### Repository submission and lifecycle

- **FR-01:** Accept a URL for an accessible public GitHub repository.
- **FR-02:** Validate the host and supported URL shape, then convert the URL to a canonical owner/repository identity.
- **FR-03:** Create an analysis job with observable queued, running, completed, and failed states.
- **FR-04:** Acquire a bounded shallow snapshot in a temporary isolated workspace and always clean it up.

### Deterministic analysis

- **FR-05:** Produce a bounded folder and file inventory without following unsafe symbolic links.
- **FR-06:** Identify programming languages, important configuration files, likely application entry points, and technology signals from concrete file evidence.
- **FR-07:** Inspect README, LICENSE, CONTRIBUTING, test files or configuration, and `.env.example`-style documentation signals.
- **FR-08:** Extract basic classes and functions from supported Python and TypeScript files using Tree-sitter.
- **FR-09:** Derive basic module-dependency and code-organization signals within the explicitly supported languages.
- **FR-10:** Generate deterministic documentation, project-readiness, code-organization, and maintainability findings.
- **FR-11:** Attach a stable rule ID, category, severity, description, machine-readable evidence, bounded score impact, and recommendation to every finding.

### Scoring and report delivery

- **FR-12:** Calculate versioned category scores and an overall health score from documented deterministic rules.
- **FR-13:** Identify important files and entry points and produce onboarding guidance grounded in analyzed facts.
- **FR-14:** Prioritize improvements according to severity and score impact.
- **FR-15:** Show analysis progress and the completed report in an accessible web dashboard.
- **FR-16:** Export the same report data as versioned JSON and human-readable Markdown.

## MVP report expectations

A completed report should include:

- repository identity and analyzed commit or snapshot identifier;
- schema and scoring versions;
- file counts, languages, technology signals, important files, and likely entry points;
- documentation and test-readiness signals;
- supported Python and TypeScript symbols and basic module relationships;
- category scores and a bounded overall health score;
- evidence-backed findings and prioritized recommendations;
- onboarding guidance based only on verified analysis facts;
- links or endpoints for JSON and Markdown export.

The health score is an onboarding and readiness indicator, not an absolute judgment of software quality.

## Non-functional requirements

### Security and privacy

- Never execute repository code, scripts, dependencies, hooks, tests, builds, macros, or binaries.
- Restrict acquisition to the documented public GitHub URL policy and defend against SSRF and unsafe redirects.
- Enforce repository-size, file-count, individual-file-size, parser-time, and total-job-time limits.
- Ignore or safely classify binary and excluded content; do not traverse symbolic links outside the workspace.
- Retain source only temporarily and remove it on every success or failure path.
- Persist derived metadata and reports, not full source snapshots.
- Keep credentials, tokens, and source bodies out of logs.
- Confine repository acquisition to a non-root, read-only worker with bounded writable storage, dropped capabilities, no-new-privileges, and explicit memory, CPU, and PID limits.
- Separate worker data access from web and API traffic; enforce domain-specific egress in deployment infrastructure rather than pretending Docker Compose provides a DNS allowlist.

### Reliability and explainability

- Long-running analysis must use a background job rather than hold an HTTP request open.
- Jobs and state transitions should be idempotent where retries can occur.
- Parser failures for one supported file must be isolated and represented without crashing the entire job.
- Scoring rules, report schemas, and scoring versions must be documented and tested against fixed fixtures.
- API errors and unsupported repositories must produce actionable, non-sensitive messages.

### Quality and usability

- Important behavior requires automated tests.
- CI must enforce formatting, linting, type checks, tests, and the frontend production build.
- The dashboard must provide keyboard-accessible controls, meaningful status feedback, and readable findings.
- The architecture and local development workflow must remain approachable to junior contributors.

## MVP acceptance outcomes

The MVP is usable when a person can submit a supported public GitHub URL, observe a background analysis through its lifecycle, inspect a stable evidence-backed report, understand every score impact, and download equivalent JSON and Markdown representations. No analyzed code is executed or retained after the analysis workspace is cleaned.

## Explicitly out of scope for the first release

- Private repositories and organization-only access
- GitHub OAuth or user accounts
- Pull request, issue, or commit-history analysis
- Automatic GitHub issue creation
- Executing repository code, dependencies, tests, or builds in any sandbox
- Advanced SAST, secret scanning, malware detection, or vulnerability assessment
- Deep syntax analysis beyond the first supported Python and TypeScript scope
- Sending a complete repository to an AI model
- AI chat or ungrounded AI-generated findings
- Long-term source-code or full-repository snapshot storage
- Teams, workspaces, subscriptions, payments, or billing

These exclusions are product boundaries, not implied deficiencies. Adding one requires an explicit future milestone and a security review.

## Assumptions

- The first release analyzes only accessible public repositories hosted on `github.com`.
- Basic acquisition works without a token for accessible public repositories and never prompts for credentials.
- Analysis can exceed an interactive HTTP timeout, so queue-backed processing is required.
- Repository and analysis limits will be public, explicit, and configurable.
- PostgreSQL stores analysis metadata and derived reports; Redis supports transient job transport.
- Anonymous single-user interaction is sufficient for the initial dashboard.
- Database schema changes will use migrations from the first persistence milestone.
