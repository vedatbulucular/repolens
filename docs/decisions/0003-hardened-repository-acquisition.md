# ADR 0003: Hardened shallow clone for repository acquisition

- **Status:** Accepted
- **Date:** 2026-07-21

## Context

Stage 2 must temporarily acquire an accessible public GitHub repository without executing repository-provided code or retaining source. The worker must discover the remote default branch without using the GitHub REST or GraphQL API, enforce resource limits, remain safe under task redelivery, and remove all temporary data after success, failure, timeout, or cancellation.

GitHub source archives would avoid a Git executable, but they require a known branch, tag, or commit reference. Safe extraction would also add redirect, archive-bomb, path traversal, link, and special-entry handling. Repository settings can cause GitHub archives to include actual Git LFS objects rather than pointers.

## Decision

RepoLens Stage 2A uses the worker image's trusted Git executable to perform a depth-one, single-branch, tags-free HTTPS clone of the canonical URL stored in PostgreSQL. The submitted raw URL never reaches acquisition and the stored URL is revalidated immediately before work begins.

Git runs through a subprocess argument list rather than a shell. The process receives an allowlisted environment with terminal prompts, LFS smudging, system configuration, user-selected protocols, credential helpers, submodule recursion, file and ext protocols, repository hooks, and HTTP redirects disabled. Standard output and standard error are discarded and are never logged or persisted.

Each attempt uses a deterministic `analysis-<uuid>` direct child of a trusted absolute workspace root. Workspaces are deleted before creation to recover from redelivery and again from a `finally` block. Paths are checked for containment before recursive deletion. Git metadata is removed before the source safety pass.

The safety pass uses `lstat` semantics and never follows untrusted links. Stage 2A rejects every symbolic link, including links that would otherwise remain inside the repository. This conservative MVP rule avoids platform-specific link resolution and ensures Stage 3 cannot accidentally follow a retained link. FIFO, socket, device, and other non-regular entries are also rejected.

Acquisition enforces timeout, complete-workspace size, checked-out regular-file size, entry count, individual-file size, path length, and path-depth limits. The Docker worker adds a hard tmpfs bound as defense in depth. It persists only a safe error code and message; source, filenames, Git output, URLs used by Git, and system paths are not copied into errors or logs.

Celery's message identifier is stored as an internal processing token through a short atomic state update. A redelivery of the same message may resume a processing analysis, while a different delivery cannot claim it. Acquisition runs after the claim transaction and database connection have been released. Completion and failure use a new short conditional update that succeeds only while the analysis is still processing and owned by the same token. Late acknowledgments, worker-lost rejection, and cancellation of long-running tasks after broker connection loss preserve redelivery without a row-level or advisory lock during network and filesystem work.

## Consequences

- The worker image requires Git and trusted CA certificates; the API image does not.
- Renamed repositories that require an HTTP redirect fail safely and must be submitted using their current canonical URL.
- Repositories containing symbolic links are rejected in Stage 2A, even if the links are internal and safe.
- Git network bytes cannot be limited exactly before receipt, so process monitoring and a bounded tmpfs provide layered controls.
- Repository source is unavailable after the acquisition task completes. Later analysis stages must operate inside the same temporary workspace context rather than persist or reopen it.

## Deferred to Stage 2B

Stage 2B may add a read-only container root filesystem, dropped Linux capabilities, explicit PID and memory limits, and deployment-specific network egress enforcement. Those controls strengthen containment but do not replace the application-level URL, Git, process, filesystem, and cleanup policies established here.
