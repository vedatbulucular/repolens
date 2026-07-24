"""Versioned HTTP endpoints for analysis lifecycle records."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from repolens_api.analysis_results import SUPPORTED_RESULT_SCHEMA_VERSIONS
from repolens_api.database import get_session
from repolens_api.errors import problem, problem_response
from repolens_api.models import Analysis, AnalysisResult, AnalysisStatus
from repolens_api.repository_urls import InvalidRepositoryUrl, parse_repository_url
from repolens_api.schemas import (
    AnalysisCreateRequest,
    AnalysisResponse,
    AnalysisResultResponse,
    InventoryPayloadResponse,
    InventoryPayloadV2Response,
    InventoryPayloadV3Response,
    RepositoryResponse,
)
from repolens_api.services import (
    create_analysis_record,
    get_analysis_record,
    get_analysis_result_record,
    mark_analysis_failed,
)
from repolens_api.tasks import enqueue_analysis

AnalysisDispatcher = Callable[[UUID], None]

router = APIRouter(prefix="/api/v1")


def get_analysis_dispatcher() -> AnalysisDispatcher:
    """Return the production Celery dispatcher for dependency injection."""
    return enqueue_analysis


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _optional_as_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _as_utc(value)


def _analysis_response(analysis: Analysis) -> AnalysisResponse:
    return AnalysisResponse(
        id=analysis.id,
        status=analysis.status.value,
        requested_at=_as_utc(analysis.requested_at),
        started_at=_optional_as_utc(analysis.started_at),
        completed_at=_optional_as_utc(analysis.completed_at),
        error_message=analysis.error_message,
        error_code=analysis.error_code,
        repository=RepositoryResponse.model_validate(analysis.repository),
    )


def _analysis_result_response(
    analysis: Analysis,
    result: AnalysisResult,
) -> AnalysisResultResponse:
    try:
        payload: InventoryPayloadResponse | InventoryPayloadV2Response | InventoryPayloadV3Response
        if result.schema_version == 3:
            payload = InventoryPayloadV3Response.model_validate(result.payload)
        elif result.schema_version == 2:
            payload = InventoryPayloadV2Response.model_validate(result.payload)
        else:
            payload = InventoryPayloadResponse.model_validate(result.payload)
    except ValidationError:
        raise problem(
            type_="analysis_result_invalid",
            title="Analysis result invalid",
            status=500,
            detail="The stored analysis result is invalid.",
        ) from None

    return AnalysisResultResponse(
        analysis_id=analysis.id,
        result_schema_version=result.schema_version,
        repository=RepositoryResponse.model_validate(analysis.repository),
        repository_summary=payload.repository_summary,
        languages=payload.languages,
        important_files=payload.important_files,
        technologies=payload.technologies,
        entry_points=payload.entry_points,
        warnings=payload.warnings,
        code_structure=(
            payload.code_structure if isinstance(payload, InventoryPayloadV2Response) else None
        ),
        quality_findings=(
            payload.quality_findings if isinstance(payload, InventoryPayloadV3Response) else None
        ),
        requested_at=_as_utc(analysis.requested_at),
        started_at=_optional_as_utc(analysis.started_at),
        completed_at=_optional_as_utc(analysis.completed_at),
    )


@router.post(
    "/analyses",
    response_model=AnalysisResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        422: problem_response("Invalid repository URL or request"),
        503: problem_response("Database or analysis queue unavailable"),
    },
)
async def create_analysis(
    payload: AnalysisCreateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    dispatcher: Annotated[AnalysisDispatcher, Depends(get_analysis_dispatcher)],
) -> AnalysisResponse:
    """Create and enqueue one analysis lifecycle record."""
    try:
        identity = parse_repository_url(payload.repository_url)
    except InvalidRepositoryUrl as exc:
        raise problem(
            type_="invalid_repository_url",
            title="Invalid repository URL",
            status=422,
            detail="Only public HTTPS GitHub repository URLs are supported.",
        ) from exc

    try:
        analysis = await create_analysis_record(session, identity)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise problem(
            type_="database_error",
            title="Database operation failed",
            status=503,
            detail="The analysis could not be stored. Please try again later.",
        ) from exc

    try:
        dispatcher(analysis.id)
    except Exception as exc:
        try:
            await mark_analysis_failed(
                session,
                analysis.id,
                "Analysis queue dispatch failed.",
            )
        except SQLAlchemyError:
            await session.rollback()
        raise problem(
            type_="analysis_queue_unavailable",
            title="Analysis queue unavailable",
            status=503,
            detail="The analysis could not be queued. Please try again later.",
        ) from exc

    return _analysis_response(analysis)


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisResponse,
    responses={
        404: problem_response("Analysis not found"),
        422: problem_response("Invalid analysis identifier"),
        503: problem_response("Database unavailable"),
    },
)
async def get_analysis(
    analysis_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnalysisResponse:
    """Return the current state of an analysis record."""
    try:
        analysis = await get_analysis_record(session, analysis_id)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise problem(
            type_="database_error",
            title="Database operation failed",
            status=503,
            detail="The analysis could not be loaded. Please try again later.",
        ) from exc

    if analysis is None:
        raise problem(
            type_="analysis_not_found",
            title="Analysis not found",
            status=404,
            detail="No analysis exists for the supplied identifier.",
        )

    return _analysis_response(analysis)


@router.get(
    "/analyses/{analysis_id}/result",
    response_model=AnalysisResultResponse,
    responses={
        404: problem_response("Analysis not found"),
        409: problem_response("Analysis is not ready or failed"),
        422: problem_response("Invalid analysis identifier"),
        500: problem_response("Analysis result unavailable"),
        503: problem_response("Database unavailable"),
    },
)
async def get_analysis_result(
    analysis_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnalysisResultResponse:
    """Return the typed persisted result for one completed analysis."""
    try:
        analysis = await get_analysis_record(session, analysis_id)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise problem(
            type_="database_error",
            title="Database operation failed",
            status=503,
            detail="The analysis result could not be loaded. Please try again later.",
        ) from exc

    if analysis is None:
        raise problem(
            type_="analysis_not_found",
            title="Analysis not found",
            status=404,
            detail="No analysis exists for the supplied identifier.",
        )
    if analysis.status in {AnalysisStatus.QUEUED, AnalysisStatus.PROCESSING}:
        raise problem(
            type_="analysis_not_ready",
            title="Analysis result not ready",
            status=409,
            detail="The analysis result is not ready.",
        )
    if analysis.status is AnalysisStatus.FAILED:
        raise problem(
            type_="analysis_failed",
            title="Analysis failed",
            status=409,
            detail="The analysis did not produce a result.",
            error_code=analysis.error_code,
        )

    try:
        result = await get_analysis_result_record(session, analysis_id)
    except SQLAlchemyError as exc:
        await session.rollback()
        raise problem(
            type_="database_error",
            title="Database operation failed",
            status=503,
            detail="The analysis result could not be loaded. Please try again later.",
        ) from exc
    if result is None:
        raise problem(
            type_="analysis_result_missing",
            title="Analysis result missing",
            status=500,
            detail="The completed analysis result is unavailable.",
        )
    if result.schema_version not in SUPPORTED_RESULT_SCHEMA_VERSIONS:
        raise problem(
            type_="unsupported_result_schema",
            title="Unsupported analysis result schema",
            status=500,
            detail="The stored analysis result schema is not supported.",
        )
    return _analysis_result_response(analysis, result)
