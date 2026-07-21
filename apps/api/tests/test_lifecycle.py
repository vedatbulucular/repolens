"""Tests for analysis state transitions and acquisition task behavior."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api.acquisition.errors import AcquisitionTimeout, CleanupFailed
from repolens_api.lifecycle import InvalidStatusTransition, transition_analysis
from repolens_api.models import Analysis, AnalysisStatus, Repository
from repolens_api.tasks import process_analysis


def test_valid_lifecycle_transitions_set_timestamps_and_clear_errors() -> None:
    analysis = Analysis(repository_id=uuid4(), status=AnalysisStatus.QUEUED)
    started_at = datetime(2026, 7, 21, 10, tzinfo=UTC)
    completed_at = datetime(2026, 7, 21, 11, tzinfo=UTC)

    transition_analysis(analysis, AnalysisStatus.PROCESSING, occurred_at=started_at)
    transition_analysis(analysis, AnalysisStatus.COMPLETED, occurred_at=completed_at)

    assert analysis.status is AnalysisStatus.COMPLETED
    assert analysis.started_at == started_at
    assert analysis.completed_at == completed_at
    assert analysis.error_message is None
    assert analysis.error_code is None


def test_invalid_lifecycle_transition_is_blocked() -> None:
    existing_error = "Existing safe error"
    analysis = Analysis(
        repository_id=uuid4(),
        status=AnalysisStatus.QUEUED,
        error_message=existing_error,
    )

    with pytest.raises(InvalidStatusTransition):
        transition_analysis(analysis, AnalysisStatus.COMPLETED)

    assert analysis.status is AnalysisStatus.QUEUED
    assert analysis.started_at is None
    assert analysis.completed_at is None
    assert analysis.error_message == existing_error


async def _create_analysis(
    sessions: async_sessionmaker[AsyncSession],
    *,
    status: AnalysisStatus = AnalysisStatus.QUEUED,
    canonical_url: str = "https://github.com/openai/openai-python",
    processing_token: str | None = None,
    started_at: datetime | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
) -> Analysis:
    async with sessions() as session:
        repository = Repository(
            canonical_url=canonical_url,
            owner="openai",
            name="openai-python",
        )
        analysis = Analysis(
            repository=repository,
            status=status,
            processing_token=processing_token,
            started_at=started_at,
            error_code=error_code,
            error_message=error_message,
        )
        session.add(analysis)
        await session.commit()
        return analysis


async def _load_analysis(
    sessions: async_sessionmaker[AsyncSession],
    analysis_id: UUID,
) -> Analysis:
    async with sessions() as session:
        analysis = await session.get(Analysis, analysis_id)
        assert analysis is not None
        return analysis


def test_worker_uses_database_canonical_url_and_completes(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))
    received: list[tuple[UUID, str]] = []

    async def acquire(analysis_id: UUID, canonical_url: str) -> None:
        received.append((analysis_id, canonical_url))

    asyncio.run(process_analysis(analysis.id, "delivery-1", sessions=test_sessions, work=acquire))

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert received == [(analysis.id, "https://github.com/openai/openai-python")]
    assert persisted.status is AnalysisStatus.COMPLETED
    assert persisted.started_at is not None
    assert persisted.completed_at is not None
    assert persisted.processing_token is None


def test_invalid_stored_url_fails_without_starting_work(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(
        _create_analysis(
            test_sessions,
            canonical_url="https://github.com/openai/openai-python.git",
        )
    )
    calls = 0

    async def acquire(_analysis_id: UUID, _canonical_url: str) -> None:
        nonlocal calls
        calls += 1

    asyncio.run(process_analysis(analysis.id, "delivery-1", sessions=test_sessions, work=acquire))

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert calls == 0
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.error_code == "acquisition_failed"


def test_worker_records_safe_timeout(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def timeout(_analysis_id: UUID, _canonical_url: str) -> None:
        raise AcquisitionTimeout

    asyncio.run(process_analysis(analysis.id, "delivery-1", sessions=test_sessions, work=timeout))

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.error_code == "acquisition_timeout"
    assert persisted.error_message == "Repository acquisition exceeded the allowed time."


def test_unexpected_failure_is_sanitized(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def fail(_analysis_id: UUID, _canonical_url: str) -> None:
        raise RuntimeError("credential and private system path")

    asyncio.run(process_analysis(analysis.id, "delivery-1", sessions=test_sessions, work=fail))

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.error_code == "acquisition_failed"
    assert persisted.error_message == "Repository acquisition failed."
    assert "credential" not in persisted.error_message


def test_terminal_task_retry_is_noop(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def acquire(_analysis_id: UUID, _canonical_url: str) -> None:
        return None

    asyncio.run(process_analysis(analysis.id, "delivery-1", sessions=test_sessions, work=acquire))
    first_result = asyncio.run(_load_analysis(test_sessions, analysis.id))
    asyncio.run(process_analysis(analysis.id, "delivery-2", sessions=test_sessions, work=acquire))
    second_result = asyncio.run(_load_analysis(test_sessions, analysis.id))

    assert second_result.status is AnalysisStatus.COMPLETED
    assert second_result.started_at == first_result.started_at
    assert second_result.completed_at == first_result.completed_at
    assert second_result.processing_token is None


def test_processing_task_redelivery_with_same_token_resumes(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    original_started_at = datetime(2026, 7, 21, 12, tzinfo=UTC)
    analysis = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="delivery-1",
            started_at=original_started_at,
        )
    )
    before_redelivery = asyncio.run(_load_analysis(test_sessions, analysis.id))
    calls = 0

    async def acquire(_analysis_id: UUID, _canonical_url: str) -> None:
        nonlocal calls
        calls += 1

    asyncio.run(process_analysis(analysis.id, "delivery-1", sessions=test_sessions, work=acquire))

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert calls == 1
    assert persisted.status is AnalysisStatus.COMPLETED
    assert persisted.started_at == before_redelivery.started_at


def test_processing_task_with_different_token_is_noop(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(
        _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="active-delivery",
        )
    )
    calls = 0

    async def acquire(_analysis_id: UUID, _canonical_url: str) -> None:
        nonlocal calls
        calls += 1

    asyncio.run(
        process_analysis(analysis.id, "duplicate-delivery", sessions=test_sessions, work=acquire)
    )

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert calls == 0
    assert persisted.status is AnalysisStatus.PROCESSING
    assert persisted.processing_token == "active-delivery"


class TrackingSessionFactory:
    """Track task-owned session contexts around acquisition work."""

    def __init__(self, delegate: async_sessionmaker[AsyncSession]) -> None:
        self._delegate = delegate
        self.active_contexts = 0

    def __call__(self) -> AbstractAsyncContextManager[AsyncSession]:
        return self._open()

    @asynccontextmanager
    async def _open(self) -> AsyncIterator[AsyncSession]:
        self.active_contexts += 1
        try:
            async with self._delegate() as session:
                yield session
        finally:
            self.active_contexts -= 1


def test_database_session_is_released_during_acquisition_and_claim_fields_are_consistent(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(
        _create_analysis(
            test_sessions,
            error_code="old_error",
            error_message="Old safe error.",
        )
    )
    tracking_sessions = TrackingSessionFactory(test_sessions)

    async def acquire(_analysis_id: UUID, _canonical_url: str) -> None:
        assert tracking_sessions.active_contexts == 0
        during_acquisition = await _load_analysis(test_sessions, analysis.id)
        assert during_acquisition.status is AnalysisStatus.PROCESSING
        assert during_acquisition.started_at is not None
        assert during_acquisition.completed_at is None
        assert during_acquisition.error_code is None
        assert during_acquisition.error_message is None
        assert during_acquisition.processing_token == "delivery-1"

    asyncio.run(
        process_analysis(
            analysis.id,
            "delivery-1",
            sessions=tracking_sessions,
            work=acquire,
        )
    )

    assert tracking_sessions.active_contexts == 0
    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.COMPLETED
    assert persisted.completed_at is not None


def test_two_different_tokens_racing_only_run_the_owner(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))
    calls: list[str] = []

    async def exercise() -> None:
        owner_started = asyncio.Event()
        release_owner = asyncio.Event()

        async def owner_work(_analysis_id: UUID, _canonical_url: str) -> None:
            calls.append("owner")
            owner_started.set()
            await release_owner.wait()

        async def duplicate_work(_analysis_id: UUID, _canonical_url: str) -> None:
            calls.append("duplicate")

        owner_task = asyncio.create_task(
            process_analysis(
                analysis.id,
                "owner-token",
                sessions=test_sessions,
                work=owner_work,
            )
        )
        await owner_started.wait()
        await process_analysis(
            analysis.id,
            "duplicate-token",
            sessions=test_sessions,
            work=duplicate_work,
        )
        release_owner.set()
        await owner_task

    asyncio.run(exercise())

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert calls == ["owner"]
    assert persisted.status is AnalysisStatus.COMPLETED


@pytest.mark.parametrize("raises_failure", [False, True])
def test_old_worker_cannot_finalize_after_processing_token_changes(
    test_sessions: async_sessionmaker[AsyncSession],
    raises_failure: bool,
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def replaced_owner(_analysis_id: UUID, _canonical_url: str) -> None:
        async with test_sessions() as session:
            persisted = await session.get(Analysis, analysis.id)
            assert persisted is not None
            persisted.processing_token = "new-owner-token"
            await session.commit()
        if raises_failure:
            raise AcquisitionTimeout

    asyncio.run(
        process_analysis(
            analysis.id,
            "old-owner-token",
            sessions=test_sessions,
            work=replaced_owner,
        )
    )

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.PROCESSING
    assert persisted.processing_token == "new-owner-token"
    assert persisted.completed_at is None
    assert persisted.error_code is None


def test_cleanup_failure_never_completes_analysis(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_analysis(test_sessions))

    async def cleanup_failure(_analysis_id: UUID, _canonical_url: str) -> None:
        raise CleanupFailed

    asyncio.run(
        process_analysis(
            analysis.id,
            "delivery-1",
            sessions=test_sessions,
            work=cleanup_failure,
        )
    )

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.error_code == "cleanup_failed"
    assert persisted.error_message == "The temporary repository workspace could not be removed."
    assert persisted.processing_token is None
