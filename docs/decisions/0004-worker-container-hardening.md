# ADR 0004: Worker container hardening

- **Status:** Accepted
- **Date:** 2026-07-22

## Context

The Celery worker is the only RepoLens service that retrieves and handles untrusted repository content. Stage 2A prevents repository-provided execution and enforces URL, process, filesystem, size, and cleanup policies, but its development container still had a writable root filesystem, a broad writable source mount, default Linux capabilities, unrestricted process and memory growth, and a shared application network.

Container controls are defense in depth. They must reduce the impact of a Git or application defect without weakening the rule that repository code is never executed. They must also preserve the documented native and Docker development workflows.

## Decision

### Least privilege and read-only storage

The worker continues to run as UID/GID 65534. Docker Compose drops every Linux capability, enables no-new-privileges, retains Docker's default seccomp profile, and mounts the root filesystem read-only. The worker receives only the application source as a read-only bind mount; the broader backend directory is not exposed.

The only application-controlled writable mounts are:

- `/tmp/repolens-workspaces`, a 640 MiB tmpfs owned by UID/GID 65534 with mode 0700;
- `/tmp/repolens-runtime`, a 64 MiB tmpfs owned by UID/GID 65534 with mode 0700.

Both mounts use noexec, nosuid, and nodev. `HOME` and the general temporary-directory variables point to the runtime tmpfs. The acquisition workspace root is fixed inside Compose and cannot be redirected by a host `.env` file. Git continues to put its global configuration, disabled hooks directory, and temporary files inside the per-analysis repository workspace. Container shared memory is explicitly limited to 64 MiB.

### Resource limits

The default worker uses concurrency 2, 1536 MiB of memory, 2 CPUs, and 64 PIDs. Each acquisition permits at most 256 MiB of complete workspace data, so two concurrent attempts require at most 512 MiB before polling overhead. The 640 MiB workspace tmpfs leaves bounded headroom for Git metadata and polling delay. Because tmpfs pages count toward container memory, the memory limit also leaves room for Celery, Python, two Git process trees, runtime tmpfs, and shared memory.

These values are development defaults exposed as documented `REPOLENS_WORKER_*` Compose variables. Operators who change concurrency or per-task workspace size must preserve the capacity relationship and leave process-memory headroom. RepoLens does not disable the OOM killer and does not claim that an OOM can always be converted into an application error.

### Networks and development ports

The web and API share a frontend network. The API and worker use separate internal data networks to reach PostgreSQL and Redis, preventing the worker from directly reaching the web or API containers. Only the worker joins a non-internal egress network for public HTTPS GitHub access.

PostgreSQL and Redis keep host port mappings for the supported native development workflow, but those ports bind only to `127.0.0.1`. Docker Compose can isolate complete networks but cannot safely enforce a DNS-name allowlist for GitHub's changing addresses and delivery infrastructure. Domain-specific egress restrictions therefore remain a deployment firewall or controlled-proxy responsibility. Stage 2B adds neither a proxy nor a custom firewall.

### Shutdown and redelivery

Compose continues to send SIGTERM, allowing Celery warm shutdown. A 90-second stop grace period exceeds the 60-second acquisition subprocess timeout and leaves time for process termination, workspace cleanup, and the final PostgreSQL transition.

Late acknowledgment, worker-lost rejection, cancellation on broker connection loss, and a prefetch multiplier of one remain enabled. Redis broker visibility is set to 300 seconds. A worker child loss can therefore requeue an unacknowledged task, while complete container loss becomes visible again within a bounded interval. The same Celery delivery identifier remains the processing token, so a redelivery can resume its own processing claim, clear a stale deterministic workspace, and avoid rerunning terminal analyses.

Repeated worker loss can cause repeated delivery. Stage 2B does not add retry counters, dead-letter storage, database models, or migrations. PostgreSQL remains the only source of truth for analysis lifecycle state, and the Celery result backend remains disabled.

### Images and health checks

The API and worker Docker targets remain separate. Git and trusted CA certificates are installed only in the worker target with no recommended packages, and APT package lists are removed in the same layer. The worker target ends as UID/GID 65534. Health checks use the existing Python, Celery, and Git executables to confirm that Git exists, the worker responds through the broker, and `repolens.process_analysis` is registered. No health-only network or capability tools are added.

## Consequences

- Repository content cannot be written outside bounded temporary mounts through normal worker filesystem access.
- Checked-out executable bits do not make repository files executable on the workspace tmpfs.
- Worker compromise has no ambient Linux capabilities and cannot gain privileges through setuid execution.
- Resource exhaustion is bounded per container, but a too-low memory limit may kill a worker before it records a safe failure.
- A forced container loss may leave an analysis processing until Redis visibility expires and a replacement worker consumes the same message.
- Local source edits remain visible through a narrow read-only source mount, but other backend files and local secrets are no longer exposed to the worker.
- Worker egress remains destination-unrestricted at Compose level. Production-grade domain egress, custom seccomp/AppArmor profiles, Kubernetes policies, and cloud controls require separate deployment work.
