"""Celery tasks for safe repository acquisition."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api.acquisition.errors import AcquisitionError, AcquisitionErrorCode
from repolens_api.acquisition.git import GitRepositoryClient
from repolens_api.acquisition.processes import SubprocessRunner
from repolens_api.acquisition.service import RepositoryAcquisitionService
from repolens_api.acquisition.workspace import WorkspaceManager
from repolens_api.celery_app import celery_app
from repolens_api.database import create_engine, session_factory
from repolens_api.repository_urls import InvalidRepositoryUrl, parse_repository_url
from repolens_api.services import (
    claim_analysis_for_processing,
    complete_claimed_analysis,
    fail_claimed_analysis,
)
from repolens_api.settings import get_settings

AcquisitionWork = Callable[[UUID, str], Awaitable[None]]
SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class CeleryTaskRequest(Protocol):
    """Typed subset of Celery request metadata used for redelivery ownership."""

    id: str


class BoundCeleryTask(Protocol):
    """Typed subset of a bound Celery task."""

    request: CeleryTaskRequest


async def _acquire_repository(analysis_id: UUID, canonical_url: str) -> None:
    """Build the production acquisition service for one task event loop."""
    settings = get_settings()
    service = RepositoryAcquisitionService(
        workspaces=WorkspaceManager(settings.workspace_root),
        git=GitRepositoryClient(SubprocessRunner()),
        limits=settings.acquisition_limits(),
    )
    await service.acquire(analysis_id, canonical_url)


async def process_analysis(
    analysis_id: UUID,
    processing_token: str,
    *,
    sessions: SessionFactory = session_factory,
    work: AcquisitionWork = _acquire_repository,
) -> None:
    """Claim, acquire, clean, and finish one analysis idempotently."""
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
        await work(claim.id, claim.repository.canonical_url)
    except AcquisitionError as exc:
        async with sessions() as failure_session:
            await fail_claimed_analysis(
                failure_session,
                analysis_id,
                processing_token,
                error_code=exc.code.value,
                error_message=exc.public_message,
            )
        return
    except Exception:
        async with sessions() as failure_session:
            await fail_claimed_analysis(
                failure_session,
                analysis_id,
                processing_token,
                error_code=AcquisitionErrorCode.ACQUISITION_FAILED.value,
                error_message="Repository acquisition failed.",
            )
        return

    async with sessions() as completion_session:
        await complete_claimed_analysis(completion_session, analysis_id, processing_token)


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
