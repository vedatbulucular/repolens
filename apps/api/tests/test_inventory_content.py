"""Tests for bounded binary and UTF-8 content reads."""

import errno
import os
from dataclasses import replace
from pathlib import Path

import pytest

from repolens_api.inventory.content import SafeContentReader
from repolens_api.inventory.contracts import (
    ContentStatus,
    InventoryLimits,
    InventoryWarningCode,
)
from repolens_api.inventory.errors import UnsafeRepositoryPath
from repolens_api.inventory.policy import is_sensitive_file


@pytest.mark.parametrize(
    "content",
    [
        b"\x89PNG\r\n\x1a\nrest",
        b"\xff\xd8\xffrest",
        b"PK\x03\x04archive",
        b"\x7fELFbinary",
    ],
)
def test_binary_magic_prefix_is_detected(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    content: bytes,
) -> None:
    path = tmp_path / "asset"
    path.write_bytes(content)

    result = SafeContentReader(inventory_limits).inspect_binary(
        tmp_path,
        "asset",
        expected_size=len(content),
    )

    assert result.is_binary is True
    assert result.content_status is ContentStatus.BINARY


def test_nul_byte_in_sample_is_binary(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    path = tmp_path / "unknown.dat"
    path.write_bytes(b"text\x00binary")

    result = SafeContentReader(inventory_limits).inspect_binary(
        tmp_path,
        "unknown.dat",
        expected_size=path.stat().st_size,
    )

    assert result.is_binary is True


@pytest.mark.parametrize(
    ("content", "expected"),
    [(b"hello", "hello"), (b"\xef\xbb\xbfhello", "hello")],
)
def test_safe_text_reader_accepts_utf8_and_utf8_bom(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    content: bytes,
    expected: str,
) -> None:
    path = tmp_path / "text"
    path.write_bytes(content)

    result = SafeContentReader(inventory_limits).read_text(
        tmp_path,
        "text",
        expected_size=len(content),
    )

    assert result.text == expected
    assert result.content_status is ContentStatus.AVAILABLE


def test_safe_text_reader_rejects_unsupported_encoding(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    path = tmp_path / "latin.txt"
    path.write_bytes(b"caf\xe9")

    result = SafeContentReader(inventory_limits).read_text(
        tmp_path,
        "latin.txt",
        expected_size=4,
    )

    assert result.text is None
    assert result.content_status is ContentStatus.UNSUPPORTED_ENCODING
    assert result.warning is not None
    assert result.warning.code is InventoryWarningCode.UNSUPPORTED_FILE_ENCODING
    assert "caf" not in result.warning.message


def test_safe_text_reader_does_not_return_nul_content(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    path = tmp_path / "nul.txt"
    path.write_bytes(b"text\x00value")

    result = SafeContentReader(inventory_limits).read_text(
        tmp_path,
        "nul.txt",
        expected_size=path.stat().st_size,
    )

    assert result.text is None
    assert result.content_status is ContentStatus.BINARY


def test_safe_text_reader_does_not_open_oversized_file(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "large.txt"
    path.write_bytes(b"large")

    def fail_open(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("oversized file must not be opened")

    monkeypatch.setattr(os, "open", fail_open)
    result = SafeContentReader(replace(inventory_limits, max_text_read_bytes=4)).read_text(
        tmp_path,
        "large.txt",
        expected_size=5,
    )

    assert result.content_status is ContentStatus.TOO_LARGE
    assert result.warning is not None
    assert result.warning.code is InventoryWarningCode.CONTENT_TOO_LARGE


@pytest.mark.parametrize("name", [".env", ".env.example", "id_rsa", "secret.pem"])
def test_sensitive_file_is_never_opened(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    path = tmp_path / name
    path.write_text("secret-value", encoding="utf-8")

    def fail_open(*_args: object, **_kwargs: object) -> int:
        raise AssertionError("sensitive file must not be opened")

    monkeypatch.setattr(os, "open", fail_open)
    reader = SafeContentReader(inventory_limits)

    binary = reader.inspect_binary(tmp_path, name, expected_size=path.stat().st_size)
    text = reader.read_text(tmp_path, name, expected_size=path.stat().st_size)

    assert binary.content_status is ContentStatus.SENSITIVE
    assert binary.warning is None
    assert text.content_status is ContentStatus.SENSITIVE
    assert text.warning is None


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.production",
        ".env.example",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_xmss",
        "private.pem",
        "private.key",
        "certificate.p12",
        "certificate.pfx",
        "keystore.jks",
        "credentials.json",
        "database-credential.yaml",
        "service-account.json",
        "service_account.toml",
        "serviceaccount.json",
        ".npmrc",
        ".pypirc",
        ".netrc",
    ],
)
def test_sensitive_filename_policy(name: str) -> None:
    assert is_sensitive_file(name)


def test_open_permission_failure_returns_safe_unreadable_warning(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "blocked.txt"
    path.write_text("private content", encoding="utf-8")

    def deny_open(*_args: object, **_kwargs: object) -> int:
        raise PermissionError(errno.EACCES, "private operating-system detail")

    monkeypatch.setattr(os, "open", deny_open)
    result = SafeContentReader(inventory_limits).inspect_binary(
        tmp_path,
        "blocked.txt",
        expected_size=path.stat().st_size,
    )

    assert result.is_binary is None
    assert result.content_status is ContentStatus.UNREADABLE
    assert result.warning is not None
    assert result.warning.code is InventoryWarningCode.FILE_UNREADABLE
    assert "private" not in result.warning.message
    assert str(tmp_path) not in result.warning.message


def test_reader_rejects_metadata_size_change(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    path = tmp_path / "changed.txt"
    path.write_text("changed", encoding="utf-8")

    with pytest.raises(UnsafeRepositoryPath):
        SafeContentReader(inventory_limits).inspect_binary(
            tmp_path,
            "changed.txt",
            expected_size=1,
        )


def test_reader_rejects_non_regular_post_open_metadata(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "changed.txt"
    path.write_text("changed", encoding="utf-8")
    directory_stat = os.stat(tmp_path)
    monkeypatch.setattr(os, "fstat", lambda _fd: directory_stat)

    with pytest.raises(UnsafeRepositoryPath):
        SafeContentReader(inventory_limits).inspect_binary(
            tmp_path,
            "changed.txt",
            expected_size=path.stat().st_size,
        )


def test_reader_uses_o_nofollow_when_supported(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow == 0:
        pytest.skip("O_NOFOLLOW is not available")
    path = tmp_path / "safe.txt"
    path.write_text("safe", encoding="utf-8")
    real_open = os.open
    observed_flags: list[int] = []

    def record_open(target: str | bytes | os.PathLike[str] | os.PathLike[bytes], flags: int) -> int:
        observed_flags.append(flags)
        return real_open(target, flags)

    monkeypatch.setattr(os, "open", record_open)
    SafeContentReader(inventory_limits).inspect_binary(
        tmp_path,
        "safe.txt",
        expected_size=path.stat().st_size,
    )

    assert observed_flags[0] & nofollow


def test_reader_rejects_symlink_without_following_it(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    target = tmp_path / "target.txt"
    target.write_text("target", encoding="utf-8")
    link = tmp_path / "link.txt"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is not available")

    with pytest.raises(UnsafeRepositoryPath):
        SafeContentReader(inventory_limits).read_text(
            tmp_path,
            "link.txt",
            expected_size=target.stat().st_size,
        )
