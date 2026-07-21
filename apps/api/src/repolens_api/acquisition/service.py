"""Orchestration for one bounded, temporary repository acquisition."""

from uuid import UUID

from repolens_api.acquisition.contracts import AcquisitionLimits, AcquisitionSummary
from repolens_api.acquisition.errors import AcquisitionError, RepositoryTooLarge
from repolens_api.acquisition.git import GitRepositoryClient
from repolens_api.acquisition.processes import directory_size
from repolens_api.acquisition.validation import validate_repository_tree
from repolens_api.acquisition.workspace import WorkspaceManager
from repolens_api.repository_urls import InvalidRepositoryUrl, parse_repository_url


class RepositoryAcquisitionService:
    """Acquire, validate, and remove one untrusted repository snapshot."""

    def __init__(
        self,
        *,
        workspaces: WorkspaceManager,
        git: GitRepositoryClient,
        limits: AcquisitionLimits,
    ) -> None:
        self._workspaces = workspaces
        self._git = git
        self._limits = limits

    async def acquire(self, analysis_id: UUID, canonical_url: str) -> AcquisitionSummary:
        """Acquire a repository temporarily and return only aggregate counters."""
        self._validate_canonical_url(canonical_url)
        async with self._workspaces.temporary_workspace(analysis_id) as workspace:
            await self._git.clone(canonical_url, workspace, self._limits)
            workspace_bytes = directory_size(workspace.root)
            if workspace_bytes > self._limits.max_workspace_bytes:
                raise RepositoryTooLarge
            self._workspaces.remove_git_metadata(workspace)
            validation = validate_repository_tree(workspace.repository, self._limits)
            return AcquisitionSummary(
                repository_bytes=validation.repository_bytes,
                workspace_bytes=workspace_bytes,
                entry_count=validation.entry_count,
            )

    @staticmethod
    def _validate_canonical_url(canonical_url: str) -> None:
        try:
            identity = parse_repository_url(canonical_url)
        except InvalidRepositoryUrl as exc:
            raise AcquisitionError from exc
        if identity.canonical_url != canonical_url:
            raise AcquisitionError
