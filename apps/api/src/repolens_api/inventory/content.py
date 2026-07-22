"""Bounded readers for untrusted regular repository files."""

import errno
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from repolens_api.inventory.contracts import (
    ContentStatus,
    InventoryLimits,
    InventoryWarning,
    InventoryWarningCode,
)
from repolens_api.inventory.errors import UnsafeRepositoryPath
from repolens_api.inventory.policy import is_sensitive_file, validate_relative_path

BINARY_MAGIC_PREFIXES: tuple[bytes, ...] = (
    b"\x7fELF",
    b"MZ",
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
    b"Rar!\x1a\x07",
    b"\x1f\x8b",
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"%PDF-",
    b"7z\xbc\xaf\x27\x1c",
    b"SQLite format 3\x00",
)


@dataclass(frozen=True, slots=True)
class BinaryInspection:
    """Safe outcome of a bounded binary sample."""

    is_binary: bool | None
    content_status: ContentStatus
    warning: InventoryWarning | None = None


@dataclass(frozen=True, slots=True)
class TextReadResult:
    """Safe outcome of a bounded UTF-8 text read."""

    text: str | None
    content_status: ContentStatus
    warning: InventoryWarning | None = None


def _warning(
    code: InventoryWarningCode,
    relative_path: str,
    message: str,
) -> InventoryWarning:
    return InventoryWarning(code=code, relative_path=relative_path, message=message)


class SafeContentReader:
    """Open only expected regular files and never expose read failures."""

    def __init__(self, limits: InventoryLimits) -> None:
        self._limits = limits

    def inspect_binary(
        self,
        repository_root: Path,
        relative_path: str,
        *,
        expected_size: int,
    ) -> BinaryInspection:
        """Classify a bounded sample as binary, text-like, or unreadable."""
        normalized = self._validated_relative(relative_path)
        if is_sensitive_file(normalized):
            return BinaryInspection(None, ContentStatus.SENSITIVE)

        fd = self._open_regular(repository_root, normalized, expected_size)
        if fd is None:
            return BinaryInspection(
                None,
                ContentStatus.UNREADABLE,
                _warning(
                    InventoryWarningCode.FILE_UNREADABLE,
                    normalized,
                    "The file content could not be read safely.",
                ),
            )

        try:
            sample = self._read_up_to(fd, min(expected_size, self._limits.binary_sample_bytes))
        except OSError:
            return BinaryInspection(
                None,
                ContentStatus.UNREADABLE,
                _warning(
                    InventoryWarningCode.FILE_UNREADABLE,
                    normalized,
                    "The file content could not be read safely.",
                ),
            )
        finally:
            os.close(fd)

        is_binary = b"\x00" in sample or any(
            sample.startswith(prefix) for prefix in BINARY_MAGIC_PREFIXES
        )
        status = ContentStatus.BINARY if is_binary else ContentStatus.AVAILABLE
        return BinaryInspection(is_binary, status)

    def read_text(
        self,
        repository_root: Path,
        relative_path: str,
        *,
        expected_size: int,
        max_bytes: int | None = None,
    ) -> TextReadResult:
        """Read one complete, bounded UTF-8 file after metadata verification."""
        normalized = self._validated_relative(relative_path)
        if is_sensitive_file(normalized):
            return TextReadResult(None, ContentStatus.SENSITIVE)

        limit = max_bytes if max_bytes is not None else self._limits.max_text_read_bytes
        if limit <= 0:
            raise ValueError("text read limit must be positive")
        if expected_size > limit:
            return TextReadResult(
                None,
                ContentStatus.TOO_LARGE,
                _warning(
                    InventoryWarningCode.CONTENT_TOO_LARGE,
                    normalized,
                    "The file exceeds the allowed text-read size.",
                ),
            )

        fd = self._open_regular(repository_root, normalized, expected_size)
        if fd is None:
            return TextReadResult(
                None,
                ContentStatus.UNREADABLE,
                _warning(
                    InventoryWarningCode.FILE_UNREADABLE,
                    normalized,
                    "The file content could not be read safely.",
                ),
            )

        try:
            content = self._read_up_to(fd, expected_size + 1)
        except OSError:
            return TextReadResult(
                None,
                ContentStatus.UNREADABLE,
                _warning(
                    InventoryWarningCode.FILE_UNREADABLE,
                    normalized,
                    "The file content could not be read safely.",
                ),
            )
        finally:
            os.close(fd)

        if len(content) != expected_size:
            raise UnsafeRepositoryPath
        if b"\x00" in content:
            return TextReadResult(None, ContentStatus.BINARY)
        try:
            text = content.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            return TextReadResult(
                None,
                ContentStatus.UNSUPPORTED_ENCODING,
                _warning(
                    InventoryWarningCode.UNSUPPORTED_FILE_ENCODING,
                    normalized,
                    "The file uses an unsupported text encoding.",
                ),
            )
        return TextReadResult(text, ContentStatus.AVAILABLE)

    def _validated_relative(self, relative_path: str) -> str:
        return validate_relative_path(
            PurePosixPath(relative_path),
            self._limits.max_path_length,
        )

    @staticmethod
    def _read_up_to(fd: int, maximum: int) -> bytes:
        chunks: list[bytes] = []
        remaining = maximum
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _open_regular(
        repository_root: Path,
        relative_path: str,
        expected_size: int,
    ) -> int | None:
        path = repository_root.joinpath(*PurePosixPath(relative_path).parts)
        try:
            before = os.stat(path, follow_symlinks=False)
        except OSError:
            raise UnsafeRepositoryPath from None
        if not stat.S_ISREG(before.st_mode) or before.st_size != expected_size:
            raise UnsafeRepositoryPath

        flags = os.O_RDONLY
        flags |= getattr(os, "O_BINARY", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EPERM}:
                return None
            try:
                after_failure = os.stat(path, follow_symlinks=False)
            except OSError:
                raise UnsafeRepositoryPath from None
            if (
                not stat.S_ISREG(after_failure.st_mode)
                or after_failure.st_size != expected_size
                or (before.st_dev, before.st_ino) != (after_failure.st_dev, after_failure.st_ino)
            ):
                raise UnsafeRepositoryPath from None
            return None

        try:
            after = os.fstat(fd)
            if (
                not stat.S_ISREG(after.st_mode)
                or after.st_size != expected_size
                or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            ):
                raise UnsafeRepositoryPath
        except BaseException:
            os.close(fd)
            raise
        return fd
