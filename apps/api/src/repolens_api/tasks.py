"""Celery tasks for safe repository acquisition."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api.acquisition.errors import AcquisitionError
from repolens_api.acquisition.git import GitRepositoryClient
from repolens_api.acquisition.processes import SubprocessRunner
from repolens_api.acquisition.service import RepositoryAcquisitionService
from repolens_api.acquisition.workspace import WorkspaceManager
from repolens_api.analysis_results import (
    AnalysisResultPersistenceError,
    AnalysisResultSerializationError,
)
from repolens_api.celery_app import celery_app
from repolens_api.database import create_engine, session_factory
from repolens_api.inventory.contracts import InventoryResult
from repolens_api.inventory.errors import InventoryError, RepositoryAnalysisFailed
from repolens_api.inventory.service import INVENTORY_SCHEMA_VERSION, InventoryService
from repolens_api.repository_urls import InvalidRepositoryUrl, parse_repository_url
from repolens_api.services import (
    claim_analysis_for_processing,
    fail_claimed_analysis,
    finalize_analysis_with_result,
)
from repolens_api.settings import get_settings

AnalysisWork = Callable[[UUID, str], Awaitable[InventoryResult]]
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class CeleryTaskRequest(Protocol):
    """Typed subset of Celery request metadata used for redelivery ownership."""

    id: str


class BoundCeleryTask(Protocol):
    """Typed subset of a bound Celery task."""

    request: CeleryTaskRequest


async def _analyze_repository(analysis_id: UUID, canonical_url: str) -> InventoryResult:
    """Acquire and inventory one repository before its workspace is removed."""
    settings = get_settings()
    acquisition = RepositoryAcquisitionService(
        workspaces=WorkspaceManager(settings.workspace_root),
        git=GitRepositoryClient(SubprocessRunner()),
        limits=settings.acquisition_limits(),
    )
    inventory = InventoryService(settings.inventory_limits())
    async with acquisition.acquire_workspace(analysis_id, canonical_url) as repository_root:
        return inventory.analyze(repository_root)


async def process_analysis(
    analysis_id: UUID,
    processing_token: str,
    *,
    sessions: SessionFactory = session_factory,
    work: AnalysisWork = _analyze_repository,
) -> None:
    """Claim, analyze, clean, and atomically finalize one analysis."""
    async with sessions() as claim_session:
        claim = await claim_analysis_for_processing(
            claim_session,
            analysis_id,
            processing_token,
        )
    if claim is None:
        return

    try:
        try:
            identity = parse_repository_url(claim.repository.canonical_url)
        except InvalidRepositoryUrl as exc:
            raise AcquisitionError from exc
        if identity.canonical_url != claim.repository.canonical_url:
            raise AcquisitionError
        inventory_result = await work(claim.id, claim.repository.canonical_url)
    except (AcquisitionError, InventoryError) as exc:
        await _record_failure(
            sessions,
            analysis_id,
            processing_token,
            error_code=exc.code.value,
            error_message=exc.public_message,
        )
        return
    except Exception:
        failure = RepositoryAnalysisFailed()
        await _record_failure(
            sessions,
            analysis_id,
            processing_token,
            error_code=failure.code.value,
            error_message=failure.public_message,
        )
        return

    settings = get_settings()
    try:
        async with sessions() as finalization_session:
            await finalize_analysis_with_result(
                finalization_session,
                analysis_id,
                processing_token,
                inventory_result,
                schema_version=INVENTORY_SCHEMA_VERSION,
                max_result_bytes=settings.max_result_bytes,
            )
    except (AnalysisResultSerializationError, AnalysisResultPersistenceError) as exc:
        await _record_failure(
            sessions,
            analysis_id,
            processing_token,
            error_code=exc.code.value,
            error_message=exc.public_message,
        )


async def _record_failure(
    sessions: SessionFactory,
    analysis_id: UUID,
    processing_token: str,
    *,
    error_code: str,
    error_message: str,
) -> None:
    async with sessions() as failure_session:
        await fail_claimed_analysis(
            failure_session,
            analysis_id,
            processing_token,
            error_code=error_code,
            error_message=error_message,
        )


async def _process_with_task_engine(analysis_id: UUID, processing_token: str) -> None:
    """Run a task with an engine owned by its one asyncio event loop."""
    task_engine = create_engine(get_settings().database_url)
    task_sessions = async_sessionmaker(task_engine, expire_on_commit=False)
    try:
        await process_analysis(
            analysis_id,
            processing_token,
            sessions=task_sessions,
        )
    finally:
        await task_engine.dispose()


@celery_app.task(bind=True, name="repolens.process_analysis")  # type: ignore[untyped-decorator]
def process_analysis_task(task: BoundCeleryTask, analysis_id: str) -> None:
    """Celery entry point containing only the analysis identifier payload."""
    processing_token = str(task.request.id)
    asyncio.run(_process_with_task_engine(UUID(analysis_id), processing_token))


def enqueue_analysis(analysis_id: UUID) -> None:
    """Publish one analysis job to Celery."""
    process_analysis_task.delay(str(analysis_id))
