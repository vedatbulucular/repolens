"""Small immutable contracts shared by repository acquisition modules."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AcquisitionLimits:
    """Resource limits enforced while acquiring one repository."""

    timeout_seconds: int
    max_repository_bytes: int
    max_workspace_bytes: int
    max_file_count: int
    max_file_bytes: int
    max_path_length: int
    max_path_depth: int


@dataclass(frozen=True, slots=True)
class AcquisitionSummary:
    """Non-sensitive aggregate facts produced by a successful acquisition."""

    repository_bytes: int
    workspace_bytes: int
    entry_count: int
