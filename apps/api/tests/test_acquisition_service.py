"""Integration tests for temporary acquisition orchestration."""

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from repolens_api.acquisition.contracts import AcquisitionLimits
from repolens_api.acquisition.errors import (
    AcquisitionError,
    AcquisitionTimeout,
    CleanupFailed,
)
from repolens_api.acquisition.git import GitRepositoryClient
from repolens_api.acquisition.processes import (
    ProcessRequest,
    ProcessResult,
    ProcessTimedOut,
)
from repolens_api.acquisition.service import RepositoryAcquisitionService
from repolens_api.acquisition.workspace import WorkspaceManager


def _limits() -> AcquisitionLimits:
    return AcquisitionLimits(
        timeout_seconds=1,
        max_repository_bytes=100,
        max_workspace_bytes=1_000,
        max_file_count=10,
        max_file_bytes=100,
        max_path_length=100,
        max_path_depth=10,
    )


class FixtureCloneRunner:
    def __init__(self, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.calls = 0

    async def run(self, request: ProcessRequest) -> ProcessResult:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        destination = Path(request.arguments[-1])
        (destination / ".git").mkdir(parents=True)
        (destination / ".git" / "config").write_text(
            "remote contains sensitive URL metadata",
            encoding="utf-8",
        )
        (destination / "README.md").write_text("safe fixture", encoding="utf-8")
        return ProcessResult(0)


def _service(tmp_path: Path, runner: FixtureCloneRunner) -> RepositoryAcquisitionService:
    return RepositoryAcquisitionService(
        workspaces=WorkspaceManager(tmp_path.resolve()),
        git=GitRepositoryClient(runner),
        limits=_limits(),
    )


def _workspace_path(tmp_path: Path, analysis_id: UUID) -> Path:
    return tmp_path / f"analysis-{analysis_id}"


def test_service_acquires_validates_and_cleans_repository(tmp_path: Path) -> None:
    analysis_id = uuid4()
    runner = FixtureCloneRunner()

    summary = asyncio.run(
        _service(tmp_path, runner).acquire(
            analysis_id,
            "https://github.com/openai/openai-python",
        )
    )

    assert summary.repository_bytes == len("safe fixture")
    assert summary.entry_count == 1
    assert summary.workspace_bytes >= summary.repository_bytes
    assert runner.calls == 1
    assert not _workspace_path(tmp_path, analysis_id).exists()


def test_service_yields_validated_repository_until_context_exit(tmp_path: Path) -> None:
    analysis_id = uuid4()
    workspace_path = _workspace_path(tmp_path, analysis_id)

    async def exercise() -> None:
        async with _service(tmp_path, FixtureCloneRunner()).acquire_workspace(
            analysis_id,
            "https://github.com/openai/openai-python",
        ) as repository_root:
            assert repository_root == workspace_path / "repository"
            assert repository_root.is_dir()
            assert (repository_root / "README.md").read_text(encoding="utf-8") == "safe fixture"
            assert not (repository_root / ".git").exists()
            assert workspace_path.exists()

    asyncio.run(exercise())
    assert not workspace_path.exists()


def test_workspace_context_removes_stale_attempt_before_clone(tmp_path: Path) -> None:
    analysis_id = uuid4()
    workspace_path = _workspace_path(tmp_path, analysis_id)
    workspace_path.mkdir()
    stale_marker = workspace_path / "stale-private-data.txt"
    stale_marker.write_text("stale", encoding="utf-8")

    async def exercise() -> None:
        async with _service(tmp_path, FixtureCloneRunner()).acquire_workspace(
            analysis_id,
            "https://github.com/openai/openai-python",
        ) as repository_root:
            assert repository_root.is_dir()
            assert not stale_marker.exists()

    asyncio.run(exercise())
    assert not workspace_path.exists()


def test_inventory_exception_cleans_acquired_workspace(tmp_path: Path) -> None:
    analysis_id = uuid4()

    async def exercise() -> None:
        async with _service(tmp_path, FixtureCloneRunner()).acquire_workspace(
            analysis_id,
            "https://github.com/openai/openai-python",
        ):
            raise RuntimeError("private inventory detail")

    with pytest.raises(RuntimeError, match="private inventory detail"):
        asyncio.run(exercise())
    assert not _workspace_path(tmp_path, analysis_id).exists()


def test_cancellation_inside_acquired_workspace_cleans_it(tmp_path: Path) -> None:
    analysis_id = uuid4()

    async def exercise() -> None:
        async with _service(tmp_path, FixtureCloneRunner()).acquire_workspace(
            analysis_id,
            "https://github.com/openai/openai-python",
        ):
            raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(exercise())
    assert not _workspace_path(tmp_path, analysis_id).exists()


def test_context_cleanup_failure_is_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    analysis_id = uuid4()
    manager = WorkspaceManager(tmp_path.resolve())
    service = RepositoryAcquisitionService(
        workspaces=manager,
        git=GitRepositoryClient(FixtureCloneRunner()),
        limits=_limits(),
    )

    def fail_cleanup(_workspace: object) -> None:
        raise CleanupFailed

    monkeypatch.setattr(manager, "cleanup", fail_cleanup)

    async def exercise() -> None:
        async with service.acquire_workspace(
            analysis_id,
            "https://github.com/openai/openai-python",
        ):
            pass

    with pytest.raises(CleanupFailed) as raised:
        asyncio.run(exercise())
    assert str(raised.value) == "The temporary repository workspace could not be removed."
    assert str(tmp_path) not in str(raised.value)


def test_cleanup_failure_does_not_hide_inventory_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WorkspaceManager(tmp_path.resolve())
    service = RepositoryAcquisitionService(
        workspaces=manager,
        git=GitRepositoryClient(FixtureCloneRunner()),
        limits=_limits(),
    )

    def fail_cleanup(_workspace: object) -> None:
        raise CleanupFailed

    monkeypatch.setattr(manager, "cleanup", fail_cleanup)

    async def exercise() -> None:
        async with service.acquire_workspace(
            uuid4(),
            "https://github.com/openai/openai-python",
        ):
            raise RuntimeError("original inventory failure")

    with pytest.raises(RuntimeError, match="original inventory failure"):
        asyncio.run(exercise())


def test_invalid_stored_canonical_url_never_starts_git(tmp_path: Path) -> None:
    runner = FixtureCloneRunner()
    analysis_id = uuid4()

    with pytest.raises(AcquisitionError):
        asyncio.run(
            _service(tmp_path, runner).acquire(
                analysis_id,
                "https://github.com/openai/openai-python.git",
            )
        )

    assert runner.calls == 0
    assert not _workspace_path(tmp_path, analysis_id).exists()


def test_timeout_cleans_workspace(tmp_path: Path) -> None:
    runner = FixtureCloneRunner(ProcessTimedOut("untrusted process detail"))
    analysis_id = uuid4()

    with pytest.raises(AcquisitionTimeout):
        asyncio.run(
            _service(tmp_path, runner).acquire(
                analysis_id,
                "https://github.com/openai/openai-python",
            )
        )

    assert not _workspace_path(tmp_path, analysis_id).exists()


def test_cancellation_cleans_workspace(tmp_path: Path) -> None:
    runner = FixtureCloneRunner(asyncio.CancelledError())
    analysis_id = uuid4()

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(
            _service(tmp_path, runner).acquire(
                analysis_id,
                "https://github.com/openai/openai-python",
            )
        )

    assert not _workspace_path(tmp_path, analysis_id).exists()
