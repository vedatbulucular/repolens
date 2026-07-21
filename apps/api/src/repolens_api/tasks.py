"""Celery tasks for the mock Stage 1 analysis lifecycle."""

import asyncio
from collections.abc import Awaitable, Callable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api.celery_app import celery_app
from repolens_api.database import create_engine, session_factory
from repolens_api.lifecycle import transition_analysis
from repolens_api.models import Analysis, AnalysisStatus
from repolens_api.services import mark_analysis_failed
from repolens_api.settings import get_settings

MockWork = Callable[[], Awaitable[None]]


async def _complete_without_repository_work() -> None:
    """Represent successful Stage 1 work without acquiring repository content."""


async def process_mock_analysis(
    analysis_id: UUID,
    *,
    sessions: async_sessionmaker[AsyncSession] = session_factory,
    work: MockWork = _complete_without_repository_work,
) -> None:
    """Move one analysis through the mock lifecycle without external repository work."""
    try:
        async with sessions() as session:
            analysis = await session.get(Analysis, analysis_id)
            if analysis is None:
                return

            if analysis.status in Analysis.terminal_statuses:
                return

            if analysis.status is AnalysisStatus.QUEUED:
                transition_analysis(analysis, AnalysisStatus.PROCESSING)
                await session.commit()

            await work()

            transition_analysis(analysis, AnalysisStatus.COMPLETED)
            await session.commit()
    except Exception:
        async with sessions() as failure_session:
            await mark_analysis_failed(
                failure_session,
                analysis_id,
                "Analysis processing failed.",
            )
        raise


async def _process_with_task_engine(analysis_id: UUID) -> None:
    """Run a task with an engine owned by its one asyncio event loop."""
    task_engine = create_engine(get_settings().database_url)
    task_sessions = async_sessionmaker(task_engine, expire_on_commit=False)
    try:
        await process_mock_analysis(analysis_id, sessions=task_sessions)
    finally:
        await task_engine.dispose()


@celery_app.task(name="repolens.process_mock_analysis")  # type: ignore[untyped-decorator]
def process_mock_analysis_task(analysis_id: str) -> None:
    """Celery entry point for the deterministic Stage 1 mock job."""
    asyncio.run(_process_with_task_engine(UUID(analysis_id)))


def enqueue_analysis(analysis_id: UUID) -> None:
    """Publish one analysis job to Celery."""
    process_mock_analysis_task.delay(str(analysis_id))
