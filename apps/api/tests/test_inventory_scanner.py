"""Tests for deterministic, bounded repository traversal."""

import os
from dataclasses import replace
from pathlib import Path, PurePosixPath

import pytest

from repolens_api.inventory.contracts import DirectoryFileCount, InventoryLimits
from repolens_api.inventory.errors import (
    InventoryLimitExceeded,
    InventoryTimeout,
    UnsafeRepositoryPath,
)
from repolens_api.inventory.policy import IGNORED_DIRECTORY_NAMES, validate_relative_path
from repolens_api.inventory.scanner import RepositoryScanner
from repolens_api.inventory.service import InventoryService


def test_scanner_builds_repository_counts_and_directory_summary(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "src" / "nested").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "root.txt").write_text("r", encoding="utf-8")
    (tmp_path / "src" / "app.py").write_text("abc", encoding="utf-8")
    (tmp_path / "src" / "nested" / "util.py").write_text("de", encoding="utf-8")
    (tmp_path / "docs" / "README.md").write_text("docs", encoding="utf-8")

    result = InventoryService(inventory_limits).analyze(tmp_path)
    summary = result.repository_summary

    assert summary.regular_file_count == 4
    assert summary.analyzed_directory_count == 3
    assert summary.total_file_bytes == 10
    assert summary.max_directory_depth == 2
    assert summary.top_level_directories == ("docs", "src")
    assert summary.directories_by_file_count == (
        DirectoryFileCount("src", 2),
        DirectoryFileCount("docs", 1),
        DirectoryFileCount("src/nested", 1),
    )


def test_scanner_rejects_non_directory_root(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    file_root = tmp_path / "file.txt"
    file_root.touch()

    with pytest.raises(UnsafeRepositoryPath):
        RepositoryScanner(inventory_limits).scan(file_root)


def test_scanner_order_does_not_depend_on_creation_order(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for name in ("z.py", "B.py", "a.py"):
        (first / name).write_text(name, encoding="utf-8")
    for name in ("a.py", "B.py", "z.py"):
        (second / name).write_text(name, encoding="utf-8")

    first_scan = RepositoryScanner(inventory_limits).scan(first)
    second_scan = RepositoryScanner(inventory_limits).scan(second)

    assert tuple(entry.relative_path for entry in first_scan.files) == (
        "a.py",
        "B.py",
        "z.py",
    )
    assert tuple(entry.name for entry in first_scan.files) == tuple(
        entry.name for entry in second_scan.files
    )


@pytest.mark.parametrize("ignored_name", sorted(IGNORED_DIRECTORY_NAMES))
def test_ignored_directories_are_pruned_case_insensitively(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
    ignored_name: str,
) -> None:
    ignored = tmp_path / ignored_name
    (ignored / "nested").mkdir(parents=True)
    (ignored / "nested" / "hidden.py").write_text("hidden", encoding="utf-8")
    (tmp_path / "visible.py").write_text("visible", encoding="utf-8")

    scan = RepositoryScanner(inventory_limits).scan(tmp_path)

    assert tuple(entry.relative_path for entry in scan.files) == ("visible.py",)
    assert scan.directories == ()
    assert scan.ignored_directory_count == 1


def test_ignored_directory_match_is_case_insensitive(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    ignored = tmp_path / "NoDe_MoDuLeS"
    ignored.mkdir()
    (ignored / "hidden.py").write_text("hidden", encoding="utf-8")

    scan = RepositoryScanner(inventory_limits).scan(tmp_path)

    assert scan.files == ()
    assert scan.ignored_directory_count == 1


def test_repository_gitignore_is_not_interpreted(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / ".gitignore").write_text("src/\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("metadata", encoding="utf-8")

    scan = RepositoryScanner(inventory_limits).scan(tmp_path)

    assert tuple(entry.relative_path for entry in scan.files) == (".gitignore", "src/app.py")


def test_ignored_subtree_is_never_entered(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    ignored = tmp_path / "vendor"
    ignored.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    link = ignored / "unsafe-link"
    try:
        link.symlink_to(target)
    except (NotImplementedError, OSError):
        pytest.skip("symlink creation is not available")

    scan = RepositoryScanner(inventory_limits).scan(tmp_path)

    assert scan.files == ()
    assert scan.ignored_directory_count == 1


def test_scanner_rejects_symlink(
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

    with pytest.raises(UnsafeRepositoryPath, match="unsafe path"):
        RepositoryScanner(inventory_limits).scan(tmp_path)


def test_scanner_rejects_fifo_or_skips_when_unavailable(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO creation is not available")
    fifo = tmp_path / "pipe"
    try:
        os.mkfifo(fifo)
    except (NotImplementedError, OSError):
        pytest.skip("FIFO creation is not permitted")

    with pytest.raises(UnsafeRepositoryPath):
        RepositoryScanner(inventory_limits).scan(tmp_path)


def test_scanner_enforces_entry_limit(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "one.txt").touch()
    (tmp_path / "two.txt").touch()

    with pytest.raises(InventoryLimitExceeded):
        RepositoryScanner(replace(inventory_limits, max_entries=1)).scan(tmp_path)


def test_scanner_enforces_directory_limit(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()

    with pytest.raises(InventoryLimitExceeded):
        RepositoryScanner(replace(inventory_limits, max_directories=1)).scan(tmp_path)


def test_scanner_enforces_path_length(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "too-long.txt").touch()

    with pytest.raises(UnsafeRepositoryPath):
        RepositoryScanner(replace(inventory_limits, max_path_length=5)).scan(tmp_path)


def test_scanner_enforces_monotonic_timeout(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    ticks = iter((0.0, 2.0))
    scanner = RepositoryScanner(
        replace(inventory_limits, timeout_seconds=1),
        clock=lambda: next(ticks),
    )

    with pytest.raises(InventoryTimeout):
        scanner.scan(tmp_path)


@pytest.mark.parametrize(
    "relative_path",
    [
        PurePosixPath("."),
        PurePosixPath("../escape"),
        PurePosixPath("/absolute"),
        PurePosixPath("a/../b"),
        PurePosixPath("a\\b"),
    ],
)
def test_unsafe_relative_paths_are_rejected(relative_path: PurePosixPath) -> None:
    with pytest.raises(UnsafeRepositoryPath):
        validate_relative_path(relative_path, 100)


def test_scan_contract_and_error_do_not_leak_absolute_root(
    tmp_path: Path,
    inventory_limits: InventoryLimits,
) -> None:
    (tmp_path / "safe.txt").write_text("safe", encoding="utf-8")
    scan = RepositoryScanner(inventory_limits).scan(tmp_path)

    assert str(tmp_path) not in repr(scan)

    (tmp_path / "second.txt").touch()
    with pytest.raises(InventoryLimitExceeded) as raised:
        RepositoryScanner(replace(inventory_limits, max_entries=1)).scan(tmp_path)
    assert str(tmp_path) not in str(raised.value)
