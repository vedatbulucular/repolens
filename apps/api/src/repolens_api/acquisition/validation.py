"""Security-only validation of an acquired repository tree."""

import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePath

from repolens_api.acquisition.contracts import AcquisitionLimits
from repolens_api.acquisition.errors import (
    FileCountLimitExceeded,
    FileTooLarge,
    RepositoryTooLarge,
    UnsafePath,
    UnsafeSymlink,
    UnsupportedRepositoryEntry,
)


@dataclass(frozen=True, slots=True)
class ValidationSummary:
    """Aggregate counters retained only for the acquisition call."""

    repository_bytes: int
    entry_count: int


def validate_lexical_relative_path(
    relative_path: PurePath,
    *,
    max_length: int,
    max_depth: int,
) -> None:
    """Reject absolute, traversing, oversized, or overly deep paths."""
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise UnsafePath
    if len(relative_path.as_posix()) > max_length or len(relative_path.parts) > max_depth:
        raise UnsafePath


def validate_repository_tree(root: Path, limits: AcquisitionLimits) -> ValidationSummary:
    """Enforce safety limits without following links or producing an inventory."""
    if root.is_symlink() or not root.is_dir():
        raise UnsafePath

    repository_bytes = 0
    entry_count = 0
    pending = [root]
    try:
        while pending:
            current = pending.pop()
            with os.scandir(current) as entries:
                for entry in entries:
                    entry_path = Path(entry.path)
                    relative_path = entry_path.relative_to(root)
                    validate_lexical_relative_path(
                        relative_path,
                        max_length=limits.max_path_length,
                        max_depth=limits.max_path_depth,
                    )
                    entry_count += 1
                    if entry_count > limits.max_file_count:
                        raise FileCountLimitExceeded

                    entry_stat = entry.stat(follow_symlinks=False)
                    mode = entry_stat.st_mode
                    if stat.S_ISLNK(mode):
                        raise UnsafeSymlink
                    if stat.S_ISDIR(mode):
                        pending.append(entry_path)
                        continue
                    if not stat.S_ISREG(mode):
                        raise UnsupportedRepositoryEntry
                    if entry_stat.st_size > limits.max_file_bytes:
                        raise FileTooLarge
                    repository_bytes += entry_stat.st_size
                    if repository_bytes > limits.max_repository_bytes:
                        raise RepositoryTooLarge
    except (FileNotFoundError, NotADirectoryError, PermissionError) as exc:
        raise UnsafePath from exc

    return ValidationSummary(repository_bytes=repository_bytes, entry_count=entry_count)
