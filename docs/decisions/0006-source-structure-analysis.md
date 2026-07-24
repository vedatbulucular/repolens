# ADR 0006: Safe source-structure analysis

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

RepoLens needs deterministic declarations and import metadata for supported source files while treating every repository as untrusted data. Analysis must not import modules, resolve dependencies, evaluate expressions, execute scripts, or retain source text. A malformed file should normally be isolated, but unsafe paths, timeouts, and global resource-limit violations must fail the analysis without persisting a partial result.

The existing Stage 3 inventory already owns safe traversal, ignored-directory pruning, sensitive-file classification, binary inspection, size metadata, and bounded symlink-resistant reads. Source analysis should consume that inventory inside the same temporary workspace rather than introduce a second filesystem crawler.

## Decision

### Parser selection and supported languages

Python `.py` and `.pyi` files use the Python standard-library `ast` parser. It is already available, understands the running Python grammar, and creates no dependency or execution boundary. The parser calls `ast.parse`; it never imports the repository module.

TypeScript `.ts`, `.tsx`, `.mts`, and `.cts` files and JavaScript `.js`, `.jsx`, `.mjs`, and `.cjs` files use the pinned `tree-sitter`, `tree-sitter-typescript`, and `tree-sitter-javascript` packages. Only the two required grammar packages are installed. JSX and TSX select their corresponding grammar explicitly. Other languages are unsupported until a separately reviewed parser, grammar, contracts, limits, and fixtures are added.

### Data contract

The immutable result contains:

- file-level language, preserved inventory category, line and declaration counters, parse status, and syntax-error state;
- functions, async functions, classes, methods, async methods, bounded names, qualified names, line ranges, parameter counts, visibility, and reliable export flags;
- normalized modules, bounded sorted imported names, import kind, relative-import state, and line number;
- repository-wide language, file, declaration, and import counts;
- bounded fixed-code warnings.

The result deliberately excludes source text, bodies, snippets, docstrings, decorators, literal values, default parameter values, complete import statements, aliases, script commands, dependency versions, and parser diagnostics. Python exports remain false because this stage does not evaluate `__all__`. JavaScript and TypeScript exports are marked only from explicit syntax.

### Safety and limits

Source analysis reuses the inventory's `SafeContentReader`. It validates relative paths, verifies regular-file identity and expected size, does not follow symbolic links, reads a complete bounded file, accepts UTF-8 or UTF-8 BOM only, and rejects NUL content. Sensitive inventory entries are never opened. Ignored files never reach the service because inventory prunes their directories.

The worker configures a monotonic repository-wide parse deadline and explicit maxima for supported files, source-file bytes, total and per-file symbols, total and per-file imports, names per import, and warnings. Per-file symbol and import overflow is deterministically truncated with a warning. Repository-wide file, symbol, or import overflow, an unsafe path, or expiration of the total deadline is fatal and produces no result. Parser work is in-process and bounded by the file-size cap; the deadline is checked before and after each file.

Parser exceptions and syntax errors are isolated. Syntax trees that contain recoverable Tree-sitter error nodes may yield reliable declarations with `partial` status. Python syntax errors and unexpected parser failures yield no declarations for that file. Warnings contain only a code, a validated relative path, and a fixed message.

### Worker and persistence

The worker performs acquisition, inventory, manifest and evidence detection, and source-structure analysis within one validated workspace context. It holds no database transaction during repository work. The workspace and Git metadata are removed before result serialization or database finalization.

New worker results use schema version `2` and require a typed `code_structure` object. Schema version `1` remains supported for existing persisted inventory results and returns `code_structure: null` through the API. Unknown versions and malformed version 2 payloads fail with fixed safe API errors. No database migration is required because `analysis_results` already stores a separate positive schema version and a JSONB payload.

Stage 5 subsequently introduced schema version `3`, as recorded in ADR 0007. Version 3 retains the complete typed version 2 `code_structure` object and adds required `quality_findings`. Versions 1 and 2 remain readable; this later result-contract extension does not change the source-parsing decision or require a database migration.

The explicit serializer enumerates every permitted source-structure field, rejects unsafe paths and unsupported values, produces canonical JSON, and retains the existing all-or-nothing result-byte limit. Result insertion and the completed transition remain one processing-token-owned transaction, so redelivery cannot create a duplicate result.

## Consequences

- Parsing is deterministic and never executes repository content.
- Python grammar compatibility follows the worker's Python runtime; TypeScript and JavaScript grammar upgrades are explicit lockfile changes.
- Malformed individual files can produce bounded warnings without failing the repository.
- Conservative extraction may omit dynamic, computed, aliased, anonymous, or semantically resolved constructs.
- Storing derived names and module specifiers enables later deterministic rules while avoiding source retention.
- Adding a language requires a minimal parser dependency, explicit extension policy, safe output mapping, limits, fixtures, and ADR review.
- Complexity, call graphs, type or dependency resolution, scoring, AI, and frontend integration remain outside this decision.
