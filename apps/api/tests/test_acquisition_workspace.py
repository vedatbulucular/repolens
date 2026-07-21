"""Tests for bounded per-analysis temporary workspaces."""

import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

from repolens_api.acquisition.errors import CleanupFailed, UnsafePath
from repolens_api.acquisition.workspace import Workspace, WorkspaceManager


def test_workspace_is_direct_uuid_child_and_removes_stale_content(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path.resolve())
    analysis_id = uuid4()
    stale = manager.path_for(analysis_id)
    stale.mkdir()
    (stale / "stale.txt").write_text("stale", encoding="utf-8")

    workspace = manager.prepare(analysis_id)

    assert workspace.root.parent == tmp_path.resolve()
    assert workspace.root.name == f"analysis-{analysis_id}"
    assert not (workspace.root / "stale.txt").exists()
    assert workspace.global_git_config.read_bytes() == b""
    assert workspace.hooks_directory.is_dir()
    manager.cleanup(workspace)
    assert not workspace.root.exists()


def test_workspace_is_removed_after_success(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path.resolve())
    analysis_id = uuid4()

    async def exercise() -> Path:
        async with manager.temporary_workspace(analysis_id) as workspace:
            workspace.repository.mkdir()
            return workspace.root

    workspace_root = asyncio.run(exercise())
    assert not workspace_root.exists()


def test_workspace_is_removed_after_failure(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path.resolve())
    analysis_id = uuid4()
    observed_root: Path | None = None

    async def exercise() -> None:
        nonlocal observed_root
        async with manager.temporary_workspace(analysis_id) as workspace:
            observed_root = workspace.root
            raise RuntimeError("expected test failure")

    with pytest.raises(RuntimeError, match="expected test failure"):
        asyncio.run(exercise())
    assert observed_root is not None
    assert not observed_root.exists()


def test_cleanup_refuses_path_outside_workspace_root(tmp_path: Path) -> None:
    root = tmp_path / "managed"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    manager = WorkspaceManager(root.resolve())
    unsafe_workspace = Workspace(
        root=outside,
        repository=outside / "repository",
        global_git_config=outside / "gitconfig",
        hooks_directory=outside / "hooks",
    )

    with pytest.raises(UnsafePath):
        manager.cleanup(unsafe_workspace)

    assert marker.read_text(encoding="utf-8") == "keep"


def test_cleanup_failure_is_classified_without_exposing_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WorkspaceManager(tmp_path.resolve())
    workspace = manager.prepare(uuid4())

    def fail_remove(_path: Path) -> None:
        raise OSError("private system path")

    monkeypatch.setattr(shutil, "rmtree", fail_remove)
    with pytest.raises(CleanupFailed) as raised:
        manager.cleanup(workspace)
    assert "private system path" not in str(raised.value)


def test_git_metadata_removal_refuses_repository_outside_managed_workspace(
    tmp_path: Path,
) -> None:
    manager = WorkspaceManager((tmp_path / "managed").resolve())
    workspace = manager.prepare(uuid4())
    outside_repository = tmp_path / "outside"
    metadata = outside_repository / ".git"
    metadata.mkdir(parents=True)
    marker = metadata / "keep"
    marker.touch()
    unsafe_workspace = Workspace(
        root=workspace.root,
        repository=outside_repository,
        global_git_config=workspace.global_git_config,
        hooks_directory=workspace.hooks_directory,
    )

    with pytest.raises(UnsafePath):
        manager.remove_git_metadata(unsafe_workspace)

    assert marker.exists()
    manager.cleanup(workspace)
