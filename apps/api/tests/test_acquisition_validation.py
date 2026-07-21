"""Boundary and filesystem safety tests for acquired repositories."""

import os
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import cast

import pytest

from repolens_api.acquisition.contracts import AcquisitionLimits
from repolens_api.acquisition.errors import (
    FileCountLimitExceeded,
    FileTooLarge,
    RepositoryTooLarge,
    UnsafePath,
    UnsafeSymlink,
    UnsupportedRepositoryEntry,
)
from repolens_api.acquisition.validation import (
    validate_lexical_relative_path,
    validate_repository_tree,
)


def _limits(**overrides: int) -> AcquisitionLimits:
    values = {
        "timeout_seconds": 1,
        "max_repository_bytes": 10,
        "max_workspace_bytes": 20,
        "max_file_count": 2,
        "max_file_bytes": 10,
        "max_path_length": 20,
        "max_path_depth": 3,
    }
    values.update(overrides)
    return AcquisitionLimits(**values)


@pytest.mark.parametrize("size", [9, 10])
def test_file_and_repository_size_at_or_below_limit_passes(tmp_path: Path, size: int) -> None:
    (tmp_path / "file.txt").write_bytes(b"x" * size)

    summary = validate_repository_tree(tmp_path, _limits())

    assert summary.repository_bytes == size
    assert summary.entry_count == 1


def test_file_size_one_above_limit_fails(tmp_path: Path) -> None:
    (tmp_path / "file.txt").write_bytes(b"x" * 11)
    with pytest.raises(FileTooLarge):
        validate_repository_tree(tmp_path, _limits(max_repository_bytes=20))


def test_repository_size_one_above_limit_fails(tmp_path: Path) -> None:
    (tmp_path / "one.txt").write_bytes(b"x" * 6)
    (tmp_path / "two.txt").write_bytes(b"x" * 5)
    with pytest.raises(RepositoryTooLarge):
        validate_repository_tree(tmp_path, _limits())


@pytest.mark.parametrize(("count", "should_fail"), [(1, False), (2, False), (3, True)])
def test_file_count_boundaries(tmp_path: Path, count: int, should_fail: bool) -> None:
    for index in range(count):
        (tmp_path / str(index)).touch()
    if should_fail:
        with pytest.raises(FileCountLimitExceeded):
            validate_repository_tree(tmp_path, _limits())
    else:
        assert validate_repository_tree(tmp_path, _limits()).entry_count == count


@pytest.mark.parametrize(("length", "should_fail"), [(4, False), (5, False), (6, True)])
def test_path_length_boundaries(tmp_path: Path, length: int, should_fail: bool) -> None:
    (tmp_path / ("x" * length)).touch()
    if should_fail:
        with pytest.raises(UnsafePath):
            validate_repository_tree(tmp_path, _limits(max_path_length=5))
    else:
        assert validate_repository_tree(tmp_path, _limits(max_path_length=5)).entry_count == 1


@pytest.mark.parametrize(("depth", "should_fail"), [(1, False), (2, False), (3, True)])
def test_path_depth_boundaries(tmp_path: Path, depth: int, should_fail: bool) -> None:
    nested = tmp_path.joinpath(*(["a"] * depth))
    nested.mkdir(parents=True)
    if should_fail:
        with pytest.raises(UnsafePath):
            validate_repository_tree(tmp_path, _limits(max_path_depth=2, max_file_count=10))
    else:
        assert (
            validate_repository_tree(
                tmp_path,
                _limits(max_path_depth=2, max_file_count=10),
            ).entry_count
            == depth
        )


def test_lexical_traversal_is_rejected() -> None:
    with pytest.raises(UnsafePath):
        validate_lexical_relative_path(
            PurePosixPath("../escape"),
            max_length=100,
            max_depth=10,
        )


def test_internal_symbolic_links_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.touch()
    link = tmp_path / "link"
    try:
        link.symlink_to("target")
    except OSError:
        pytest.skip("symbolic links are not available in this environment")
    with pytest.raises(UnsafeSymlink):
        validate_repository_tree(tmp_path, _limits(max_file_count=10))


def test_external_symbolic_links_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.touch(exist_ok=True)
    link = tmp_path / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symbolic links are not available in this environment")
    with pytest.raises(UnsafeSymlink):
        validate_repository_tree(tmp_path, _limits(max_file_count=10))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO is not supported")
def test_special_files_are_rejected(tmp_path: Path) -> None:
    fifo = tmp_path / "pipe"
    make_fifo = cast(Callable[[Path], None], os.__dict__["mkfifo"])
    make_fifo(fifo)
    with pytest.raises(UnsupportedRepositoryEntry):
        validate_repository_tree(tmp_path, _limits())
