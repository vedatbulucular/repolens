"""Integration tests for worker inventory, cleanup, and result finalization."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import NoReturn
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api import tasks
from repolens_api.analysis_results import (
    AnalysisOutput,
    AnalysisResultPersistenceError,
    PersistableAnalysisResult,
)
from repolens_api.code_structure.contracts import CodeStructureResult, SourceStructureLimits
from repolens_api.code_structure.errors import (
    SourceStructureError,
    SourceStructureFailed,
    SourceStructureLimitExceeded,
    SourceStructureTimeout,
    UnsafeSourcePath,
)
from repolens_api.inventory.contracts import InventoryLimits, InventoryResult
from repolens_api.inventory.errors import (
    InventoryError,
    InventoryLimitExceeded,
    InventoryTimeout,
    RepositoryAnalysisFailed,
    UnsafeRepositoryPath,
)
from repolens_api.inventory.service import InventoryAnalysis
from repolens_api.models import Analysis, AnalysisResult, AnalysisStatus, Repository
from repolens_api.settings import Settings
from repolens_api.tasks import process_analysis


class CountingSessionFactory:
    """Count distinct short-lived task session contexts."""

    def __init__(self, delegate: async_sessionmaker[AsyncSession]) -> None:
        self._delegate = delegate
        self.opened = 0

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AsyncSession]:
        self.opened += 1
        async with self._delegate() as session:
            yield session


async def _create_analysis(
    sessions: async_sessionmaker[AsyncSession],
    *,
    status: AnalysisStatus = AnalysisStatus.QUEUED,
    processing_token: str | None = None,
) -> Analysis:
    async with sessions() as session:
        repository = Repository(
            canonical_url=f"https://github.com/example/worker-{uuid4()}",
            owner="example",
            name="worker-fixture",
        )
        analysis = Analysis(
            repository=repository,
            status=status,
            processing_token=processing_token,
        )
        session.add(analysis)
        await session.commit()
        return analysis


async def _load_state(
    sessions: async_sessionmaker[AsyncSession],
    analysis_id: UUID,
) -> tuple[Analysis, AnalysisResult | None]:
    async with sessions() as session:
        analysis = await session.get(Analysis, analysis_id)
        assert analysis is not None
        return analysis, await session.get(AnalysisResult, analysis_id)


def test_production_work_keeps_repository_until_inventory_then_cleans(
    tmp_path: Path,
    inventory_result: InventoryResult,
    code_structure_result: CodeStructureResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    observed_limits: list[InventoryLimits] = []
    observed_structure_limits: list[SourceStructureLimits] = []
    repository_root = tmp_path / "repository"

    class FixtureAcquisitionService:
        def __init__(self, **_kwargs: object) -> None:
            pass

        @asynccontextmanager
        async def acquire_workspace(
            self,
            _analysis_id: UUID,
            _canonical_url: str,
        ) -> AsyncIterator[Path]:
            repository_root.mkdir()
            events.append("acquired")
            try:
                yield repository_root
            finally:
                events.append("cleanup")
                repository_root.rmdir()

    class FixtureInventoryService:
        def __init__(self, limits: InventoryLimits, **_kwargs: object) -> None:
            observed_limits.append(limits)

        def analyze_with_files(self, received_root: Path) -> InventoryAnalysis:
            assert received_root == repository_root
            assert repository_root.is_dir()
            events.append("inventory")
            return InventoryAnalysis(result=inventory_result, files=())

    class FixtureCodeStructureService:
        def __init__(self, limits: SourceStructureLimits, **_kwargs: object) -> None:
            observed_structure_limits.append(limits)

        def analyze(
            self,
            received_root: Path,
            files: object,
        ) -> CodeStructureResult:
            assert received_root == repository_root
            assert repository_root.is_dir()
            assert files == ()
            events.append("structure")
            return code_structure_result

    monkeypatch.setattr(tasks, "RepositoryAcquisitionService", FixtureAcquisitionService)
    monkeypatch.setattr(tasks, "InventoryService", FixtureInventoryService)
    monkeypatch.setattr(tasks, "CodeStructureService", FixtureCodeStructureService)

    result = asyncio.run(
        tasks._analyze_repository(
            uuid4(),
            "https://github.com/example/worker-fixture",
        )
    )

    assert isinstance(result, AnalysisOutput)
    assert result.schema_version == 2
    assert result.inventory is inventory_result
    assert result.code_structure is code_structure_result
    assert events == ["acquired", "inventory", "structure", "cleanup"]
    assert observed_limits == [Settings().inventory_limits()]
    assert observed_structure_limits == [Settings().source_structure_limits()]
    assert not repository_root.exists()


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        (RepositoryAnalysisFailed(), "repository_analysis_failed"),
        (InventoryLimitExceeded(), "inventory_limit_exceeded"),
        (UnsafeRepositoryPath(), "unsafe_repository_path"),
        (InventoryTimeout(), "inventory_timeout"),
        (SourceStructureFailed(), "source_structure_failed"),
        (SourceStructureLimitExceeded(), "source_structure_limit_exceeded"),
        (SourceStructureTimeout(), "source_structure_timeout"),
        (UnsafeSourcePath(), "unsafe_source_path"),
    ],
)
def test_worker_records_safe_fatal_analysis_errors_without_result(
    test_sessions: async_sessionmaker[AsyncSession],
    failure: InventoryError | SourceStructureError,
    expected_code: str,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def fail_inventory(_analysis_id: UUID, _canonical_url: str) -> NoReturn:
        raise failure

    asyncio.run(
        process_analysis(
            analysis.id,
            "delivery-owner",
            sessions=test_sessions,
            work=fail_inventory,
        )
    )

    persisted, result = asyncio.run(_load_state(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.error_code == expected_code
    assert persisted.processing_token is None
    assert result is None


def test_worker_records_serialization_failure_without_result(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))
    invalid_language = replace(inventory_result.languages[0], percentage=float("nan"))
    invalid_result = replace(inventory_result, languages=(invalid_language,))

    async def analyze(_analysis_id: UUID, _canonical_url: str) -> InventoryResult:
        return invalid_result

    asyncio.run(
        process_analysis(
            analysis.id,
            "delivery-owner",
            sessions=test_sessions,
            work=analyze,
        )
    )

    persisted, result = asyncio.run(_load_state(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.error_code == "result_serialization_failed"
    assert result is None


def test_worker_records_result_size_failure_without_partial_result(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))
    settings = Settings(max_result_bytes=1)
    monkeypatch.setattr(tasks, "get_settings", lambda: settings)

    async def analyze(_analysis_id: UUID, _canonical_url: str) -> InventoryResult:
        return inventory_result

    asyncio.run(
        process_analysis(
            analysis.id,
            "delivery-owner",
            sessions=test_sessions,
            work=analyze,
        )
    )

    persisted, result = asyncio.run(_load_state(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.error_code == "result_too_large"
    assert result is None


def test_manifest_warning_is_persisted_and_analysis_completes(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def analyze(_analysis_id: UUID, _canonical_url: str) -> InventoryResult:
        return inventory_result

    asyncio.run(
        process_analysis(
            analysis.id,
            "delivery-owner",
            sessions=test_sessions,
            work=analyze,
        )
    )

    persisted, result = asyncio.run(_load_state(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.COMPLETED
    assert result is not None
    assert result.payload["warnings"] == [
        {
            "code": "file_unreadable",
            "relative_path": "docs/notes.txt",
            "message": "The file content could not be read safely.",
        }
    ]


def test_database_finalization_failure_remains_processing_and_is_raised(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))
    counting_sessions = CountingSessionFactory(test_sessions)

    async def analyze(_analysis_id: UUID, _canonical_url: str) -> InventoryResult:
        return inventory_result

    async def fail_finalization(
        _session: AsyncSession,
        _analysis_id: UUID,
        _processing_token: str,
        _result: InventoryResult,
        *,
        schema_version: int,
        max_result_bytes: int,
    ) -> NoReturn:
        assert schema_version == 1
        assert max_result_bytes > 0
        raise SQLAlchemyError("private database detail")

    monkeypatch.setattr(tasks, "finalize_analysis_with_result", fail_finalization)

    with pytest.raises(SQLAlchemyError, match="private database detail"):
        asyncio.run(
            process_analysis(
                analysis.id,
                "delivery-owner",
                sessions=counting_sessions,
                work=analyze,
            )
        )

    persisted, result = asyncio.run(_load_state(test_sessions, analysis.id))
    assert counting_sessions.opened == 2
    assert persisted.status is AnalysisStatus.PROCESSING
    assert persisted.processing_token == "delivery-owner"
    assert persisted.completed_at is None
    assert result is None


def test_safe_non_database_persistence_failure_marks_analysis_failed(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def analyze(_analysis_id: UUID, _canonical_url: str) -> InventoryResult:
        return inventory_result

    async def fail_finalization(
        _session: AsyncSession,
        _analysis_id: UUID,
        _processing_token: str,
        _result: InventoryResult,
        *,
        schema_version: int,
        max_result_bytes: int,
    ) -> NoReturn:
        assert schema_version == 1
        assert max_result_bytes > 0
        raise AnalysisResultPersistenceError

    monkeypatch.setattr(tasks, "finalize_analysis_with_result", fail_finalization)
    asyncio.run(
        process_analysis(
            analysis.id,
            "delivery-owner",
            sessions=test_sessions,
            work=analyze,
        )
    )

    persisted, result = asyncio.run(_load_state(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.error_code == "result_persistence_failed"
    assert persisted.error_message == "The analysis result could not be persisted."
    assert result is None


def test_commit_redelivery_is_noop_and_keeps_single_result(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))
    calls = 0

    async def analyze(_analysis_id: UUID, _canonical_url: str) -> InventoryResult:
        nonlocal calls
        calls += 1
        return inventory_result

    asyncio.run(
        process_analysis(
            analysis.id,
            "same-delivery",
            sessions=test_sessions,
            work=analyze,
        )
    )
    asyncio.run(
        process_analysis(
            analysis.id,
            "same-delivery",
            sessions=test_sessions,
            work=analyze,
        )
    )

    async def result_count() -> int:
        async with test_sessions() as session:
            count = await session.scalar(select(func.count()).select_from(AnalysisResult))
            assert count is not None
            return count

    persisted, result = asyncio.run(_load_state(test_sessions, analysis.id))
    assert calls == 1
    assert persisted.status is AnalysisStatus.COMPLETED
    assert result is not None
    assert asyncio.run(result_count()) == 1


def test_real_worker_result_is_available_through_typed_endpoint(
    api_client: TestClient,
    test_sessions: async_sessionmaker[AsyncSession],
    analysis_output: AnalysisOutput,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def analyze(_analysis_id: UUID, _canonical_url: str) -> PersistableAnalysisResult:
        return analysis_output

    asyncio.run(
        process_analysis(
            analysis.id,
            "delivery-owner",
            sessions=test_sessions,
            work=analyze,
        )
    )

    response = api_client.get(f"/api/v1/analyses/{analysis.id}/result")

    assert response.status_code == 200
    body = response.json()
    assert body["repository_summary"]["regular_file_count"] == 3
    assert body["languages"][0]["name"] == "Python"
    assert body["important_files"][0]["kind"] == "readme"
    assert body["technologies"][0]["name"] == "FastAPI"
    assert body["entry_points"][0]["relative_path"] == "src/main.py"
    assert body["warnings"][0]["code"] == "file_unreadable"
    assert body["result_schema_version"] == 2
    assert body["code_structure"]["symbols"][0]["name"] == "create_app"
    assert body["code_structure"]["imports"][0]["module"] == "fastapi"
    for forbidden in (
        "delivery-owner",
        "/tmp/repolens-workspaces",
        "PRIVATE_SOURCE_BODY",
        "private database detail",
    ):
        assert forbidden not in response.text
