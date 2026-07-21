"""Tests for the hardened shallow Git adapter."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from repolens_api.acquisition.contracts import AcquisitionLimits
from repolens_api.acquisition.errors import AcquisitionTimeout, RepositoryUnavailable
from repolens_api.acquisition.git import GitRepositoryClient
from repolens_api.acquisition.processes import (
    ProcessRequest,
    ProcessResult,
    ProcessTimedOut,
)
from repolens_api.acquisition.workspace import WorkspaceManager


def _limits() -> AcquisitionLimits:
    return AcquisitionLimits(
        timeout_seconds=1,
        max_repository_bytes=100,
        max_workspace_bytes=200,
        max_file_count=10,
        max_file_bytes=50,
        max_path_length=100,
        max_path_depth=10,
    )


class RecordingRunner:
    def __init__(self, *, result: ProcessResult | Exception | None = None) -> None:
        self.result = result or ProcessResult(0)
        self.requests: list[ProcessRequest] = []

    async def run(self, request: ProcessRequest) -> ProcessResult:
        self.requests.append(request)
        if isinstance(self.result, Exception):
            raise self.result
        Path(request.arguments[-1]).mkdir()
        return self.result


def test_git_clone_uses_fixed_shallow_security_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_ASKPASS", "untrusted-helper")
    monkeypatch.setenv("GIT_SSH_COMMAND", "untrusted-command")
    monkeypatch.setenv("SSL_CERT_FILE", "untrusted-ca")
    monkeypatch.setenv("TEMP", "untrusted-temp")
    manager = WorkspaceManager(tmp_path.resolve())
    workspace = manager.prepare(uuid4())
    runner = RecordingRunner()
    client = GitRepositoryClient(runner)

    asyncio.run(client.clone("https://github.com/openai/openai-python", workspace, _limits()))

    request = runner.requests[0]
    assert request.arguments[-3:] == (
        "--",
        "https://github.com/openai/openai-python",
        str(workspace.repository),
    )
    assert request.arguments.count("--depth") == 1
    assert request.arguments[request.arguments.index("--depth") + 1] == "1"
    assert "--single-branch" in request.arguments
    assert "--no-tags" in request.arguments
    assert "--recurse-submodules" not in request.arguments
    joined_arguments = " ".join(request.arguments)
    assert "credential.helper=" in joined_arguments
    assert "submodule.recurse=false" in joined_arguments
    assert "fetch.recurseSubmodules=false" in joined_arguments
    assert "protocol.file.allow=never" in joined_arguments
    assert "protocol.ext.allow=never" in joined_arguments
    assert "http.followRedirects=false" in joined_arguments
    assert request.environment["GIT_TERMINAL_PROMPT"] == "0"
    assert request.environment["GIT_LFS_SKIP_SMUDGE"] == "1"
    assert request.environment["GIT_CONFIG_NOSYSTEM"] == "1"
    assert request.environment["GIT_ALLOW_PROTOCOL"] == "https"
    assert request.environment["GIT_PROTOCOL_FROM_USER"] == "0"
    assert request.environment["GIT_CONFIG_GLOBAL"] == str(workspace.global_git_config)
    assert "GIT_ASKPASS" not in request.environment
    assert "GIT_SSH_COMMAND" not in request.environment
    assert "SSL_CERT_FILE" not in request.environment
    assert request.environment["TEMP"] == str(workspace.root)
    assert request.environment["TMP"] == str(workspace.root)
    assert request.environment["TMPDIR"] == str(workspace.root)
    manager.cleanup(workspace)


def test_git_timeout_returns_only_safe_error(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path.resolve())
    workspace = manager.prepare(uuid4())
    client = GitRepositoryClient(RecordingRunner(result=ProcessTimedOut("secret path")))

    with pytest.raises(AcquisitionTimeout) as raised:
        asyncio.run(client.clone("https://github.com/openai/openai-python", workspace, _limits()))

    assert str(raised.value) == "Repository acquisition exceeded the allowed time."
    assert "secret" not in str(raised.value)
    manager.cleanup(workspace)


def test_git_failure_does_not_expose_process_output(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path.resolve())
    workspace = manager.prepare(uuid4())
    client = GitRepositoryClient(RecordingRunner(result=ProcessResult(128)))

    with pytest.raises(RepositoryUnavailable) as raised:
        asyncio.run(client.clone("https://github.com/openai/openai-python", workspace, _limits()))

    assert str(raised.value) == "The public repository could not be acquired."
    manager.cleanup(workspace)
