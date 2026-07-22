"""Deterministic, bounded traversal of an untrusted repository tree."""

import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    DirectoryFileCount,
    FileCategory,
    FileInventoryEntry,
    InventoryLimits,
    InventoryWarning,
    InventoryWarningCode,
)
from repolens_api.inventory.errors import (
    InventoryLimitExceeded,
    InventoryTimeout,
    UnsafeRepositoryPath,
)
from repolens_api.inventory.policy import (
    is_ignored_directory,
    path_sort_key,
    validate_relative_path,
)

MAX_DIRECTORY_FILE_COUNTS = 10


@dataclass(frozen=True, slots=True)
class RepositoryScan:
    """Safe intermediate metadata emitted by the scanner."""

    files: tuple[FileInventoryEntry, ...]
    directories: tuple[str, ...]
    max_directory_depth: int
    top_level_directories: tuple[str, ...]
    directories_by_file_count: tuple[DirectoryFileCount, ...]
    ignored_directory_count: int
    warnings: tuple[InventoryWarning, ...]


class RepositoryScanner:
    """Traverse a repository without following links or returning partial results."""

    def __init__(
        self,
        limits: InventoryLimits,
        *,
        content_reader: SafeContentReader | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits
        self._content_reader = content_reader or SafeContentReader(limits)
        self._clock = clock

    def scan(self, repository_root: Path) -> RepositoryScan:
        """Return deterministic metadata for one valid local repository root."""
        root = Path(os.path.abspath(repository_root))
        self._validate_root(root)
        deadline = self._clock() + self._limits.timeout_seconds

        files: list[FileInventoryEntry] = []
        directories: list[str] = []
        top_level_directories: list[str] = []
        warnings: list[InventoryWarning] = []
        directory_file_counts: dict[str, int] = {}
        ignored_directory_count = 0
        entry_count = 0
        max_directory_depth = 0
        pending: list[tuple[Path, PurePosixPath | None]] = [(root, None)]

        while pending:
            self._check_deadline(deadline)
            current, current_relative = pending.pop()
            self._validate_directory(current)
            try:
                with os.scandir(current) as iterator:
                    entries = sorted(iterator, key=lambda item: (item.name.casefold(), item.name))
            except OSError:
                raise UnsafeRepositoryPath from None

            child_directories: list[tuple[Path, PurePosixPath]] = []
            for entry in entries:
                self._check_deadline(deadline)
                relative = (
                    PurePosixPath(entry.name)
                    if current_relative is None
                    else current_relative / entry.name
                )
                relative_path = validate_relative_path(relative, self._limits.max_path_length)

                entry_count += 1
                if entry_count > self._limits.max_entries:
                    raise InventoryLimitExceeded

                try:
                    entry_stat = entry.stat(follow_symlinks=False)
                except OSError:
                    raise UnsafeRepositoryPath from None
                mode = entry_stat.st_mode
                if stat.S_ISLNK(mode):
                    raise UnsafeRepositoryPath
                if stat.S_ISDIR(mode):
                    if is_ignored_directory(entry.name):
                        ignored_directory_count += 1
                        continue
                    directories.append(relative_path)
                    if len(directories) > self._limits.max_directories:
                        raise InventoryLimitExceeded
                    depth = len(relative.parts)
                    max_directory_depth = max(max_directory_depth, depth)
                    directory_file_counts[relative_path] = 0
                    if depth == 1:
                        top_level_directories.append(relative_path)
                    child_directories.append((current / entry.name, relative))
                    continue
                if not stat.S_ISREG(mode):
                    raise UnsafeRepositoryPath

                inspection = self._content_reader.inspect_binary(
                    root,
                    relative_path,
                    expected_size=entry_stat.st_size,
                )
                content_status = inspection.content_status
                if (
                    inspection.is_binary is False
                    and entry_stat.st_size > self._limits.max_text_read_bytes
                ):
                    content_status = ContentStatus.TOO_LARGE
                    warnings.append(
                        InventoryWarning(
                            code=InventoryWarningCode.CONTENT_TOO_LARGE,
                            relative_path=relative_path,
                            message="The file exceeds the allowed text-read size.",
                        )
                    )
                if inspection.warning is not None:
                    warnings.append(inspection.warning)

                files.append(
                    FileInventoryEntry(
                        relative_path=relative_path,
                        name=entry.name,
                        extension=PurePosixPath(entry.name).suffix.casefold(),
                        size_bytes=entry_stat.st_size,
                        language=None,
                        category=FileCategory.OTHER,
                        is_binary=inspection.is_binary,
                        content_status=content_status,
                    )
                )
                self._increment_ancestor_counts(relative.parent, directory_file_counts)

            pending.extend(reversed(child_directories))

        ordered_files = tuple(sorted(files, key=lambda item: path_sort_key(item.relative_path)))
        ordered_directories = tuple(sorted(directories, key=path_sort_key))
        ordered_counts = tuple(
            DirectoryFileCount(relative_path=path, file_count=count)
            for path, count in sorted(
                directory_file_counts.items(),
                key=lambda item: (-item[1], *path_sort_key(item[0])),
            )[:MAX_DIRECTORY_FILE_COUNTS]
        )
        ordered_warnings = tuple(
            sorted(
                warnings,
                key=lambda warning: (
                    warning.code.value,
                    *(path_sort_key(warning.relative_path or "")),
                ),
            )
        )
        return RepositoryScan(
            files=ordered_files,
            directories=ordered_directories,
            max_directory_depth=max_directory_depth,
            top_level_directories=tuple(sorted(top_level_directories, key=path_sort_key)),
            directories_by_file_count=ordered_counts,
            ignored_directory_count=ignored_directory_count,
            warnings=ordered_warnings,
        )

    def _check_deadline(self, deadline: float) -> None:
        if self._clock() >= deadline:
            raise InventoryTimeout

    @staticmethod
    def _increment_ancestor_counts(
        parent: PurePosixPath,
        counts: dict[str, int],
    ) -> None:
        current = parent
        while current.parts:
            key = current.as_posix()
            if key in counts:
                counts[key] += 1
            current = current.parent

    @staticmethod
    def _validate_root(root: Path) -> None:
        RepositoryScanner._validate_directory(root)

    @staticmethod
    def _validate_directory(path: Path) -> None:
        try:
            directory_stat = os.stat(path, follow_symlinks=False)
        except OSError:
            raise UnsafeRepositoryPath from None
        if not stat.S_ISDIR(directory_stat.st_mode) or stat.S_ISLNK(directory_stat.st_mode):
            raise UnsafeRepositoryPath
