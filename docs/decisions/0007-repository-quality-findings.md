# ADR 0007: Deterministic repository-quality findings

- **Status:** Accepted
- **Date:** 2026-07-24

## Context

RepoLens already derives a bounded inventory, allowlisted manifest facts, technology and entry-point evidence, and supported-language source structure. The next useful onboarding output is an explainable set of repository-quality and project-readiness observations.

Analyzed repositories are untrusted. Repository code, scripts, dependencies, hooks, tests, and builds must never run. README and CI files may contain secrets, commands, expressions, very large content, unsupported encodings, or paths intended to escape the workspace. Findings therefore cannot retain free-form repository text or operating-system diagnostics.

## Decision

Stage 5 uses deterministic fixed rules and documented heuristics. Each immutable finding has a stable code, one of six categories (`documentation`, `testing`, `project_governance`, `automation`, `maintainability`, or `onboarding`), a severity (`info`, `low`, `medium`, or `high`), fixed safe title/message/recommendation text, bounded numeric evidence, and bounded repository-relative paths.

The result includes both positive signals and improvement findings. Positive findings use `info` severity and make existing project strengths visible. Improvement severities are deliberately conservative because missing community or governance files can be reasonable for small repositories.

No category or overall score is calculated in this stage. A score would require independently reviewed weights, caps, conflict handling, and versioning. The typed findings and summary counters can become inputs to that future scoring design without making today’s heuristics look more precise than they are.

README and recognized CI files are opened only through the existing symlink-resistant `SafeContentReader`. Reads:

- use inventory-provided expected sizes and safe relative paths;
- never follow symbolic links;
- accept only UTF-8 or UTF-8 BOM;
- reject NUL content and unsupported encodings;
- obey a per-document byte limit and a monotonic total deadline;
- extract only bounded counts and boolean classifications;
- discard all text before persistence.

CI signal matching ignores full-line comments and never evaluates YAML. README section matching ignores fenced code and HTML comments. No document paragraph, heading text, CI command, expression, environment value, source snippet, exception, workspace path, or processing token enters the result.

Default heuristics are centralized in typed policy:

- a README is small below 512 bytes or 8 non-empty lines;
- sparse tests require at least 10 source files and a test/source ratio below 100 per mille;
- source files above 128 KiB are oversized;
- more than 100 symbols, 50 imports, or 50 methods marks a dense file;
- one of at least 3 symbol-bearing files holding at least 60% of 20 or more symbols marks high concentration;
- 10 source-structure warnings marks a high warning count;
- at least 90% successfully parsed supported source marks structure analysis successful;
- 25 root files marks a file-dense repository root.

These thresholds are onboarding heuristics, not coverage, complexity, correctness, security, or vulnerability measurements. They are fixed, documented, deterministic, and covered at their boundaries.

Quality analysis defaults to a 15-second total deadline, 500 findings, 20 related paths per finding, 20 evidence items per finding, and 256 KiB per selected document. Overflow is deterministically truncated with a fixed warning. Fatal timeout, unsafe-path, limit, and generic failures use fixed codes and messages.

New worker results use schema version `3` and require both typed `code_structure` and typed `quality_findings`. Version `1` remains readable with both fields null. Version `2` remains readable with typed `code_structure` and null `quality_findings`. Unknown versions and malformed version 3 payloads return fixed safe API errors. The existing versioned JSONB result table needs no migration.

## Consequences

- Findings are reproducible, testable, reviewable, and safe to expose through the API.
- The result communicates strengths as well as improvement opportunities without claiming a health score.
- Rules can reuse safe existing facts and selected bounded documents without another filesystem crawler.
- Strict fixed text and numeric evidence limit expressiveness, but prevent untrusted content and diagnostics from leaking.
- Heuristics can produce false positives or miss project-specific conventions; their thresholds and limitations must remain visible.
- A future scoring milestone can version weights and caps over stable finding codes, but must not reinterpret historical results silently.
