"""Safe fatal failures raised by repository inventory operations."""

from enum import StrEnum


class InventoryErrorCode(StrEnum):
    """Machine-readable fatal inventory classifications."""

    REPOSITORY_ANALYSIS_FAILED = "repository_analysis_failed"
    INVENTORY_LIMIT_EXCEEDED = "inventory_limit_exceeded"
    UNSAFE_REPOSITORY_PATH = "unsafe_repository_path"
    INVENTORY_TIMEOUT = "inventory_timeout"


class InventoryError(Exception):
    """Base fatal inventory error with a fixed public message."""

    code = InventoryErrorCode.REPOSITORY_ANALYSIS_FAILED
    public_message = "Repository analysis failed."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class RepositoryAnalysisFailed(InventoryError):
    """Classify an unexpected inventory failure without leaking detail."""


class InventoryLimitExceeded(InventoryError):
    """Reject a repository that exceeds a bounded inventory limit."""

    code = InventoryErrorCode.INVENTORY_LIMIT_EXCEEDED
    public_message = "Repository inventory exceeds an allowed limit."


class UnsafeRepositoryPath(InventoryError):
    """Reject a path, entry type, or metadata change that is unsafe."""

    code = InventoryErrorCode.UNSAFE_REPOSITORY_PATH
    public_message = "Repository inventory contains an unsafe path."


class InventoryTimeout(InventoryError):
    """Stop inventory work after its monotonic deadline."""

    code = InventoryErrorCode.INVENTORY_TIMEOUT
    public_message = "Repository inventory exceeded the allowed time."
