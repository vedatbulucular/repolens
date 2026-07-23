"""Database operations for repository and analysis lifecycle records."""

import asyncio
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from repolens_api.analysis_results import (
    AnalysisResultErrorCode,
    AnalysisResultPersistenceError,
    AnalysisResultSerializationError,
    SerializedInventoryResult,
    prepare_inventory_result,
)
from repolens_api.inventory.contracts import InventoryResult
from repolens_api.lifecycle import transition_analysis
from repolens_api.models import Analysis, AnalysisResult, AnalysisStatus, Repository
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


async def get_analysis_result_record(
    session: AsyncSession,
    analysis_id: UUID,
) -> AnalysisResult | None:
    """Return the single persisted result for an analysis when present."""
    return await session.get(AnalysisResult, analysis_id)


async def persist_inventory_result(
    session: AsyncSession,
    analysis_id: UUID,
    processing_token: str,
    result: InventoryResult,
    *,
    schema_version: int,
    max_result_bytes: int,
) -> AnalysisResult | None:
    """Flush a result only while the caller still owns the processing analysis."""
    prepared = prepare_inventory_result(result, max_result_bytes=max_result_bytes)
    if prepared.schema_version != schema_version:
        raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED)

    analysis = await _lock_owned_processing_analysis(
        session,
        analysis_id,
        processing_token,
    )
    if analysis is None:
        return None

    persisted = await _upsert_prepared_result(session, analysis_id, prepared)
    await session.flush()
    return persisted


async def finalize_analysis_with_result(
    session: AsyncSession,
    analysis_id: UUID,
    processing_token: str,
    result: InventoryResult,
    *,
    schema_version: int,
    max_result_bytes: int,
) -> bool:
    """Atomically persist one result and complete its still-owned analysis."""
    prepared = prepare_inventory_result(result, max_result_bytes=max_result_bytes)
    if prepared.schema_version != schema_version:
        raise AnalysisResultSerializationError(AnalysisResultErrorCode.RESULT_SERIALIZATION_FAILED)

    try:
        analysis = await _lock_owned_processing_analysis(
            session,
            analysis_id,
            processing_token,
        )
        if analysis is None:
            await session.rollback()
            return False

        await _upsert_prepared_result(session, analysis_id, prepared)
        transition_analysis(analysis, AnalysisStatus.COMPLETED)
        await session.flush()
        await session.commit()
    except (AnalysisResultSerializationError, SQLAlchemyError):
        await session.rollback()
        raise
    except asyncio.CancelledError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise AnalysisResultPersistenceError from None
    return True


async def _lock_owned_processing_analysis(
    session: AsyncSession,
    analysis_id: UUID,
    processing_token: str,
) -> Analysis | None:
    statement = (
        select(Analysis)
        .where(
            Analysis.id == analysis_id,
            Analysis.status == AnalysisStatus.PROCESSING,
            Analysis.processing_token == processing_token,
        )
        .with_for_update()
    )
    return cast(Analysis | None, await session.scalar(statement))


async def _upsert_prepared_result(
    session: AsyncSession,
    analysis_id: UUID,
    prepared: SerializedInventoryResult,
) -> AnalysisResult:
    persisted = await session.get(AnalysisResult, analysis_id)
    if persisted is None:
        persisted = AnalysisResult(
            analysis_id=analysis_id,
            schema_version=prepared.schema_version,
            payload=prepared.payload,
        )
        session.add(persisted)
    else:
        persisted.schema_version = prepared.schema_version
        persisted.payload = prepared.payload
    return persisted


async def mark_analysis_failed(
    session: AsyncSession,
    analysis_id: UUID,
    error_message: str,
    error_code: str | None = None,
) -> None:
    """Mark a queued or processing analysis as failed when possible."""
    analysis = await session.get(Analysis, analysis_id)
    if analysis is None or analysis.status in Analysis.terminal_statuses:
        return

    transition_analysis(
        analysis,
        AnalysisStatus.FAILED,
        error_message=error_message,
        error_code=error_code,
    )
    await session.commit()


async def claim_analysis_for_processing(
    session: AsyncSession,
    analysis_id: UUID,
    processing_token: str,
) -> Analysis | None:
    """Atomically claim an analysis or resume its same Celery delivery."""
    now = datetime.now(UTC)
    queued_claim = await session.execute(
        update(Analysis)
        .where(
            Analysis.id == analysis_id,
            Analysis.status == AnalysisStatus.QUEUED,
        )
        .values(
            status=AnalysisStatus.PROCESSING,
            started_at=now,
            completed_at=None,
            error_message=None,
            error_code=None,
            processing_token=processing_token,
        )
        .returning(Analysis.id)
    )
    claimed_id = queued_claim.scalar_one_or_none()
    if claimed_id is not None:
        await session.commit()
        return await get_analysis_record(session, analysis_id)

    analysis = await get_analysis_record(session, analysis_id)
    if analysis is None or analysis.status in Analysis.terminal_statuses:
        await session.rollback()
        return None
    if analysis.processing_token == processing_token:
        await session.commit()
        return analysis
    if analysis.processing_token is not None:
        await session.rollback()
        return None

    legacy_claim = await session.execute(
        update(Analysis)
        .where(
            Analysis.id == analysis_id,
            Analysis.status == AnalysisStatus.PROCESSING,
            Analysis.processing_token.is_(None),
        )
        .values(processing_token=processing_token)
        .returning(Analysis.id)
    )
    claimed_id = legacy_claim.scalar_one_or_none()
    if claimed_id is None:
        await session.rollback()
        return None
    await session.commit()
    return await get_analysis_record(session, analysis_id)


async def complete_claimed_analysis(
    session: AsyncSession,
    analysis_id: UUID,
    processing_token: str,
) -> bool:
    """Complete only the processing analysis still owned by this token."""
    result = await session.execute(
        update(Analysis)
        .where(
            Analysis.id == analysis_id,
            Analysis.status == AnalysisStatus.PROCESSING,
            Analysis.processing_token == processing_token,
        )
        .values(
            status=AnalysisStatus.COMPLETED,
            completed_at=datetime.now(UTC),
            error_message=None,
            error_code=None,
            processing_token=None,
        )
        .returning(Analysis.id)
    )
    updated = result.scalar_one_or_none() is not None
    await session.commit()
    return updated


async def fail_claimed_analysis(
    session: AsyncSession,
    analysis_id: UUID,
    processing_token: str,
    *,
    error_code: str,
    error_message: str,
) -> bool:
    """Fail only the processing analysis still owned by this token."""
    result = await session.execute(
        update(Analysis)
        .where(
            Analysis.id == analysis_id,
            Analysis.status == AnalysisStatus.PROCESSING,
            Analysis.processing_token == processing_token,
        )
        .values(
            status=AnalysisStatus.FAILED,
            completed_at=datetime.now(UTC),
            error_message=error_message,
            error_code=error_code,
            processing_token=None,
        )
        .returning(Analysis.id)
    )
    updated = result.scalar_one_or_none() is not None
    await session.commit()
    return updated
