"""Safe acquisition failures that never contain untrusted details."""

from enum import StrEnum


class AcquisitionErrorCode(StrEnum):
    """Machine-readable failure classifications persisted for analyses."""

    REPOSITORY_UNAVAILABLE = "repository_unavailable"
    ACQUISITION_TIMEOUT = "acquisition_timeout"
    REPOSITORY_TOO_LARGE = "repository_too_large"
    FILE_COUNT_LIMIT_EXCEEDED = "file_count_limit_exceeded"
    FILE_TOO_LARGE = "file_too_large"
    UNSAFE_PATH = "unsafe_path"
    UNSAFE_SYMLINK = "unsafe_symlink"
    UNSUPPORTED_REPOSITORY_ENTRY = "unsupported_repository_entry"
    CLEANUP_FAILED = "cleanup_failed"
    ACQUISITION_FAILED = "acquisition_failed"


class AcquisitionError(Exception):
    """Base class with a fixed public message and error code."""

    code = AcquisitionErrorCode.ACQUISITION_FAILED
    public_message = "Repository acquisition failed."

    def __init__(self) -> None:
        super().__init__(self.public_message)


class RepositoryUnavailable(AcquisitionError):
    code = AcquisitionErrorCode.REPOSITORY_UNAVAILABLE
    public_message = "The public repository could not be acquired."


class AcquisitionTimeout(AcquisitionError):
    code = AcquisitionErrorCode.ACQUISITION_TIMEOUT
    public_message = "Repository acquisition exceeded the allowed time."


class RepositoryTooLarge(AcquisitionError):
    code = AcquisitionErrorCode.REPOSITORY_TOO_LARGE
    public_message = "The repository exceeds the allowed size."


class FileCountLimitExceeded(AcquisitionError):
    code = AcquisitionErrorCode.FILE_COUNT_LIMIT_EXCEEDED
    public_message = "The repository contains too many entries."


class FileTooLarge(AcquisitionError):
    code = AcquisitionErrorCode.FILE_TOO_LARGE
    public_message = "The repository contains a file that exceeds the allowed size."


class UnsafePath(AcquisitionError):
    code = AcquisitionErrorCode.UNSAFE_PATH
    public_message = "The repository contains an unsafe path."


class UnsafeSymlink(AcquisitionError):
    code = AcquisitionErrorCode.UNSAFE_SYMLINK
    public_message = "The repository contains an unsupported symbolic link."


class UnsupportedRepositoryEntry(AcquisitionError):
    code = AcquisitionErrorCode.UNSUPPORTED_REPOSITORY_ENTRY
    public_message = "The repository contains an unsupported filesystem entry."


class CleanupFailed(AcquisitionError):
    code = AcquisitionErrorCode.CLEANUP_FAILED
    public_message = "The temporary repository workspace could not be removed."
