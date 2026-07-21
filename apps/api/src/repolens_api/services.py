"""Database operations for repository and analysis lifecycle records."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from repolens_api.models import Analysis, AnalysisStatus, Repository
from repolens_api.repository_urls import CanonicalRepository


async def create_analysis_record(
    session: AsyncSession,
    repository_identity: CanonicalRepository,
) -> Analysis:
    """Reuse or create a repository and persist a queued analysis record."""
    repository = await session.scalar(
        select(Repository).where(Repository.canonical_url == repository_identity.canonical_url)
    )
    if repository is None:
        repository_candidate = Repository(
            canonical_url=repository_identity.canonical_url,
            owner=repository_identity.owner,
            name=repository_identity.name,
        )
        try:
            async with session.begin_nested():
                session.add(repository_candidate)
                await session.flush()
        except IntegrityError:
            repository = await session.scalar(
                select(Repository).where(
                    Repository.canonical_url == repository_identity.canonical_url
                )
            )
            if repository is None:
                raise
        else:
            repository = repository_candidate

    analysis = Analysis(repository=repository, status=AnalysisStatus.QUEUED)
    session.add(analysis)
    await session.flush()
    await session.commit()
    return analysis


async def get_analysis_record(
    session: AsyncSession,
    analysis_id: UUID,
) -> Analysis | None:
    """Return one analysis with its repository identity eagerly loaded."""
    results = await session.scalars(
        select(Analysis)
        .options(selectinload(Analysis.repository))
        .where(Analysis.id == analysis_id)
    )
    return results.one_or_none()


async def mark_analysis_failed(
    session: AsyncSession,
    analysis_id: UUID,
    error_message: str,
) -> None:
    """Mark a queued or processing analysis as failed when possible."""
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None or analysis.status in Analysis.terminal_statuses:
        return

    from repolens_api.lifecycle import transition_analysis

    transition_analysis(
        analysis,
        AnalysisStatus.FAILED,
        error_message=error_message,
    )
    await session.commit()
