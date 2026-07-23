"""Safe fatal failures for source-structure analysis."""

from enum import StrEnum


class SourceStructureErrorCode(StrEnum):
    """Machine-readable fatal source-analysis classifications."""

    SOURCE_STRUCTURE_FAILED = "source_structure_failed"
    SOURCE_STRUCTURE_TIMEOUT = "source_structure_timeout"
    SOURCE_STRUCTURE_LIMIT_EXCEEDED = "source_structure_limit_exceeded"
    UNSAFE_SOURCE_PATH = "unsafe_source_path"


class SourceStructureError(Exception):
    """Base fatal source-analysis error with a fixed public message."""

    code = SourceStructureErrorCode.SOURCE_STRUCTURE_FAILED
    public_message = "Source structure analysis failed."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SourceStructureFailed(SourceStructureError):
    """Classify an unexpected fatal analysis failure."""


class SourceStructureTimeout(SourceStructureError):
    """Stop source analysis after its monotonic deadline."""

    code = SourceStructureErrorCode.SOURCE_STRUCTURE_TIMEOUT
    public_message = "Source structure analysis exceeded the allowed time."


class SourceStructureLimitExceeded(SourceStructureError):
    """Reject a repository that exceeds a global structure limit."""

    code = SourceStructureErrorCode.SOURCE_STRUCTURE_LIMIT_EXCEEDED
    public_message = "Source structure analysis exceeds an allowed limit."


class UnsafeSourcePath(SourceStructureError):
    """Reject unsafe or changed source filesystem metadata."""

    code = SourceStructureErrorCode.UNSAFE_SOURCE_PATH
    public_message = "Source structure analysis encountered an unsafe path."
