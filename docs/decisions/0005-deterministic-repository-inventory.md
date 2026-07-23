# ADR 0005: Deterministic repository inventory and result persistence

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

RepoLens must derive useful onboarding facts from an untrusted public repository without executing repository code, installing dependencies, or retaining source. Stage 3 needs a deterministic inventory contract, evidence-based technology signals, conservative entry-point detection, and a persistence boundary that can later be integrated with the hardened worker.

The complete file inventory may contain many paths and intermediate facts. Persisting that internal structure directly would couple storage to scanner implementation details and increase the chance of retaining source-derived or unsafe values. A result also needs a stable schema, bounded serialized size, lifecycle ownership, and predictable API validation.

## Decision

### Deterministic inventory

Repository traversal is bounded by time, entry, directory, path, text-read, and manifest-read limits. Generated and dependency directories such as `.git`, `node_modules`, virtual environments, `vendor`, build output, coverage output, caches, and language-specific target directories are pruned without traversal. Symbolic links and special files remain unsafe.

Inventory and detection never run repository-provided commands, hooks, dependencies, binaries, macros, scripts, builds, or tests. Manifest readers use standard-library JSON, TOML, and XML facilities plus conservative bounded text patterns. Tree-sitter, AST parsing, function extraction, class extraction, scoring, and code-quality analysis remain later work.

Technology findings require explicit evidence. Structured dependency, SDK, reference, or plugin evidence has high confidence; file, directory, or bounded text evidence has medium confidence. Findings and evidence are deduplicated, sorted, and truncated under explicit limits. Entry-point detection uses safe manifest paths, filename conventions, directory presence, and bounded text patterns without interpreting script commands.

The complete file inventory and manifest facts remain in memory and exist only while deterministic analysis runs. They are not stored as product records.

### One versioned result per analysis

Each analysis may own at most one `AnalysisResult`. Its `analysis_id` is both the primary key and an `ON DELETE CASCADE` foreign key to `analyses.id`; no result history or surrogate identifier is added. The first persisted schema version is `1`.

PostgreSQL stores the payload as JSONB. Isolated service and API tests use SQLAlchemy's generic JSON type through a PostgreSQL JSONB type variant. The table stores the schema version and database creation timestamp separately from the derived payload.

### Explicit serialization and bounded size

Serialization enumerates every allowed `InventoryResult` field. It does not use a blind recursive dataclass conversion. Enums become string values, tuples become JSON arrays, and only JSON-compatible scalar, list, and string-keyed object values are accepted. Non-finite floats, arbitrary objects, bytes, timestamps, and absolute or traversing paths are rejected.

The persisted payload may contain repository summary metadata, languages, important-file evidence, technology findings, entry-point findings, and safe warnings. It does not contain file bodies, full file inventory entries, dependency versions, script commands, environment values, repository URLs, workspace paths, processing tokens, or analysis timestamps.

Canonical byte measurement uses UTF-8 JSON with sorted keys, fixed separators, and `allow_nan=False`. The default maximum is 2 MiB. Serialization failure and size overflow are safe all-or-nothing failures named `result_serialization_failed` and `result_too_large`; no partial or truncated payload is persisted.

### Ownership, fatal errors, and warnings

Inventory warnings are bounded non-fatal facts and may appear in a successful result. Fatal scanner and serializer failures produce no result.

The persistence primitive serializes before acquiring a database lock, then writes only while the analysis is `processing` and owned by the same processing token. The same owner may idempotently replace the single deterministic result. Another token and every non-processing state are rejected. The primitive flushes but never commits or changes lifecycle status.

The result API accepts only supported schema versions and validates stored payloads against explicit typed response models. Unknown schemas, invalid payloads, and completed analyses missing a result return fixed safe server errors. Queued, processing, and failed lifecycle states return fixed conflict responses.

## Consequences

- Equivalent inventory contracts produce identical canonical JSON bytes.
- PostgreSQL can query JSONB while SQLite remains a limited test adapter.
- Storage remains bounded and excludes source bodies and intermediate full-file inventory data.
- A one-row model simplifies idempotency but deliberately provides no result history.
- Schema evolution requires explicit supported-version handling and future migrations.
- Conservative bounded text signals can produce false positives; deeper AST analysis remains separate.
- Stage 3A-2B1 exposes persistence and API primitives but does not invoke inventory from the worker.
- Worker integration, cleanup coordination, and atomic result-plus-completion finalization require the separately approved Stage 3A-2B2 milestone.
