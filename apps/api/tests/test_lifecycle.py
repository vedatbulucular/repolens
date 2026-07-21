"""Tests for analysis state transitions and the mock worker."""

import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api.lifecycle import InvalidStatusTransition, transition_analysis
from repolens_api.models import Analysis, AnalysisStatus, Repository
from repolens_api.tasks import process_mock_analysis


def test_valid_lifecycle_transitions_set_timestamps() -> None:
    analysis = Analysis(repository_id=uuid4(), status=AnalysisStatus.QUEUED)
    started_at = datetime(2026, 7, 21, 10, tzinfo=UTC)
    completed_at = datetime(2026, 7, 21, 11, tzinfo=UTC)

    transition_analysis(
        analysis,
        AnalysisStatus.PROCESSING,
        occurred_at=started_at,
    )
    transition_analysis(
        analysis,
        AnalysisStatus.COMPLETED,
        occurred_at=completed_at,
    )

    assert analysis.status is AnalysisStatus.COMPLETED
    assert analysis.started_at == started_at
    assert analysis.completed_at == completed_at
    assert analysis.error_message is None


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


async def _create_queued_analysis(
    sessions: async_sessionmaker[AsyncSession],
) -> Analysis:
    async with sessions() as session:
        repository = Repository(
            canonical_url="https://github.com/openai/openai-python",
            owner="openai",
            name="openai-python",
        )
        analysis = Analysis(repository=repository, status=AnalysisStatus.QUEUED)
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


def test_mock_worker_completes_analysis(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_queued_analysis(test_sessions))

    asyncio.run(process_mock_analysis(analysis.id, sessions=test_sessions))

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.COMPLETED
    assert persisted.started_at is not None
    assert persisted.completed_at is not None


def test_mock_worker_records_safe_failure(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_queued_analysis(test_sessions))

    async def fail_work() -> None:
        raise RuntimeError("sensitive internal failure")

    with pytest.raises(RuntimeError, match="sensitive internal failure"):
        asyncio.run(
            process_mock_analysis(
                analysis.id,
                sessions=test_sessions,
                work=fail_work,
            )
        )

    persisted = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert persisted.status is AnalysisStatus.FAILED
    assert persisted.completed_at is not None
    assert persisted.error_message == "Analysis processing failed."


def test_mock_worker_is_idempotent_after_completion(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    analysis = asyncio.run(_create_queued_analysis(test_sessions))
    asyncio.run(process_mock_analysis(analysis.id, sessions=test_sessions))
    first_result = asyncio.run(_load_analysis(test_sessions, analysis.id))

    asyncio.run(process_mock_analysis(analysis.id, sessions=test_sessions))

    second_result = asyncio.run(_load_analysis(test_sessions, analysis.id))
    assert second_result.status is AnalysisStatus.COMPLETED
    assert second_result.started_at == first_result.started_at
    assert second_result.completed_at == first_result.completed_at
