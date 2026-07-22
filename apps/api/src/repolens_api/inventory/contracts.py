"""Immutable contracts produced by repository inventory modules."""

from dataclasses import dataclass
from enum import StrEnum


class FileCategory(StrEnum):
    """One deterministic, precedence-based file category."""

    TEST = "test"
    DOCUMENTATION = "documentation"
    DEPENDENCY_MANIFEST = "dependency_manifest"
    LOCKFILE = "lockfile"
    BUILD = "build"
    CI = "ci"
    CONFIGURATION = "configuration"
    SOURCE = "source"
    ASSET = "asset"
    DATA = "data"
    OTHER = "other"


class ContentStatus(StrEnum):
    """Safe content-inspection state for one regular file."""

    AVAILABLE = "available"
    BINARY = "binary"
    SENSITIVE = "sensitive"
    UNREADABLE = "unreadable"
    TOO_LARGE = "too_large"
    UNSUPPORTED_ENCODING = "unsupported_encoding"


class InventoryWarningCode(StrEnum):
    """Bounded warning codes that never contain untrusted detail."""

    FILE_UNREADABLE = "file_unreadable"
    UNSUPPORTED_FILE_ENCODING = "unsupported_file_encoding"
    CONTENT_TOO_LARGE = "content_too_large"
    WARNING_LIMIT_REACHED = "warning_limit_reached"


@dataclass(frozen=True, slots=True)
class InventoryLimits:
    """Resource limits enforced by one inventory operation."""

    timeout_seconds: int
    max_entries: int
    max_directories: int
    max_path_length: int
    max_manifest_bytes: int
    max_text_read_bytes: int
    binary_sample_bytes: int
    max_warnings: int


@dataclass(frozen=True, slots=True)
class FileInventoryEntry:
    """Safe metadata for one non-ignored regular repository file."""

    relative_path: str
    name: str
    extension: str
    size_bytes: int
    language: str | None
    category: FileCategory
    is_binary: bool | None
    content_status: ContentStatus


@dataclass(frozen=True, slots=True)
class DirectoryFileCount:
    """Recursive regular-file count for one analyzed directory."""

    relative_path: str
    file_count: int


@dataclass(frozen=True, slots=True)
class RepositorySummary:
    """Aggregate, metadata-only repository facts."""

    regular_file_count: int
    analyzed_directory_count: int
    total_file_bytes: int
    max_directory_depth: int
    top_level_directories: tuple[str, ...]
    directories_by_file_count: tuple[DirectoryFileCount, ...]
    ignored_directory_count: int
    binary_file_count: int
    unreadable_file_count: int
    skipped_content_file_count: int
    sensitive_file_count: int


@dataclass(frozen=True, slots=True)
class LanguageStatistic:
    """Byte-weighted statistics for one supported language."""

    name: str
    file_count: int
    total_bytes: int
    percentage: float


@dataclass(frozen=True, slots=True)
class ImportantFileGroup:
    """Bounded evidence paths for one important-file kind."""

    kind: str
    count: int
    paths: tuple[str, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class InventoryWarning:
    """A fixed, safe warning without source or operating-system detail."""

    code: InventoryWarningCode
    relative_path: str | None
    message: str


@dataclass(frozen=True, slots=True)
class InventoryResult:
    """Stage 3A-1 inventory output without persistence or later-stage facts."""

    schema_version: int
    repository_summary: RepositorySummary
    languages: tuple[LanguageStatistic, ...]
    important_files: tuple[ImportantFileGroup, ...]
    warnings: tuple[InventoryWarning, ...]
