"""Hardened shallow Git clone adapter."""

import os

from repolens_api.acquisition.contracts import AcquisitionLimits
from repolens_api.acquisition.errors import (
    AcquisitionTimeout,
    RepositoryTooLarge,
    RepositoryUnavailable,
)
from repolens_api.acquisition.processes import (
    ProcessRequest,
    ProcessRunner,
    ProcessSizeLimitExceeded,
    ProcessTimedOut,
)
from repolens_api.acquisition.workspace import Workspace

ALLOWED_ENVIRONMENT_VARIABLES = frozenset(
    {
        "COMSPEC",
        "LANG",
        "LC_ALL",
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
    }
)


class GitRepositoryClient:
    """Clone one canonical GitHub URL with a fixed security policy."""

    def __init__(self, runner: ProcessRunner, *, executable: str = "git") -> None:
        self._runner = runner
        self._executable = executable

    async def clone(
        self,
        canonical_url: str,
        workspace: Workspace,
        limits: AcquisitionLimits,
    ) -> None:
        """Create a shallow checkout without prompts, LFS, tags, or submodules."""
        request = ProcessRequest(
            arguments=self._arguments(canonical_url, workspace),
            cwd=workspace.root,
            environment=self._environment(workspace),
            timeout_seconds=limits.timeout_seconds,
            size_limit_path=workspace.root,
            max_size_bytes=limits.max_workspace_bytes,
        )
        try:
            result = await self._runner.run(request)
        except ProcessTimedOut as exc:
            raise AcquisitionTimeout from exc
        except ProcessSizeLimitExceeded as exc:
            raise RepositoryTooLarge from exc

        if result.return_code != 0:
            raise RepositoryUnavailable
        if workspace.repository.is_symlink() or not workspace.repository.is_dir():
            raise RepositoryUnavailable

    def _arguments(self, canonical_url: str, workspace: Workspace) -> tuple[str, ...]:
        return (
            self._executable,
            "-c",
            "credential.helper=",
            "-c",
            "core.hooksPath=" + str(workspace.hooks_directory),
            "-c",
            "submodule.recurse=false",
            "-c",
            "fetch.recurseSubmodules=false",
            "-c",
            "protocol.file.allow=never",
            "-c",
            "protocol.ext.allow=never",
            "-c",
            "http.followRedirects=false",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--no-tags",
            "--",
            canonical_url,
            str(workspace.repository),
        )

    def _environment(self, workspace: Workspace) -> dict[str, str]:
        environment = {
            key: value
            for key, value in os.environ.items()
            if key.upper() in ALLOWED_ENVIRONMENT_VARIABLES
        }
        environment.update(
            {
                "GIT_ALLOW_PROTOCOL": "https",
                "GIT_CONFIG_GLOBAL": str(workspace.global_git_config),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_LFS_SKIP_SMUDGE": "1",
                "GIT_PROTOCOL_FROM_USER": "0",
                "GIT_TERMINAL_PROMPT": "0",
                "TEMP": str(workspace.root),
                "TMP": str(workspace.root),
                "TMPDIR": str(workspace.root),
            }
        )
        return environment
