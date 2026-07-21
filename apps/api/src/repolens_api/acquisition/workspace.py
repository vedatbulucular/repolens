"""Creation and guaranteed cleanup of per-analysis temporary workspaces."""

import os
import shutil
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from repolens_api.acquisition.errors import CleanupFailed, UnsafePath


@dataclass(frozen=True, slots=True)
class Workspace:
    """Trusted paths created for one acquisition attempt."""

    root: Path
    repository: Path
    global_git_config: Path
    hooks_directory: Path


class WorkspaceManager:
    """Manage fixed-name workspaces below one trusted absolute root."""

    def __init__(self, root: Path) -> None:
        if not root.is_absolute():
            raise ValueError("workspace root must be absolute")
        self.root = Path(os.path.abspath(root))

    def path_for(self, analysis_id: UUID) -> Path:
        """Return the deterministic direct child used by one analysis."""
        return self.root / f"analysis-{analysis_id}"

    def _assert_direct_child(self, path: Path) -> None:
        normalized = Path(os.path.abspath(path))
        if normalized.parent != self.root or normalized == self.root:
            raise UnsafePath

    def _remove(self, path: Path) -> None:
        self._assert_direct_child(path)
        try:
            if path.is_symlink():
                path.unlink()
            elif path.exists():
                shutil.rmtree(path)
        except OSError as exc:
            raise CleanupFailed from exc

    def prepare(self, analysis_id: UUID) -> Workspace:
        """Remove a stale attempt and create fresh trusted support paths."""
        try:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if self.root.is_symlink() or not self.root.is_dir():
                raise UnsafePath
            workspace_root = self.path_for(analysis_id)
            self._remove(workspace_root)
            workspace_root.mkdir(mode=0o700)
            hooks_directory = workspace_root / "hooks"
            hooks_directory.mkdir(mode=0o700)
            global_git_config = workspace_root / "gitconfig"
            global_git_config.touch(mode=0o600)
        except (CleanupFailed, UnsafePath):
            raise
        except OSError as exc:
            raise CleanupFailed from exc

        return Workspace(
            root=workspace_root,
            repository=workspace_root / "repository",
            global_git_config=global_git_config,
            hooks_directory=hooks_directory,
        )

    def cleanup(self, workspace: Workspace) -> None:
        """Delete an exact managed workspace without following a root symlink."""
        self._remove(workspace.root)

    def remove_git_metadata(self, workspace: Workspace) -> None:
        """Remove Git metadata only from the fixed managed repository path."""
        self._assert_direct_child(workspace.root)
        repository = Path(os.path.abspath(workspace.repository))
        if repository.parent != workspace.root or repository.name != "repository":
            raise UnsafePath
        metadata = Path(os.path.abspath(repository / ".git"))
        if metadata.parent != repository or metadata.name != ".git":
            raise UnsafePath
        if metadata.is_symlink() or not metadata.is_dir():
            raise UnsafePath
        try:
            shutil.rmtree(metadata)
        except OSError as exc:
            raise UnsafePath from exc

    @asynccontextmanager
    async def temporary_workspace(self, analysis_id: UUID) -> AsyncIterator[Workspace]:
        """Yield a fresh workspace and remove it on every exit path."""
        workspace = self.prepare(analysis_id)
        try:
            yield workspace
        finally:
            self.cleanup(workspace)
