"""Model and ownership tests for persisted analysis results."""

import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api import services
from repolens_api.analysis_results import (
    AnalysisResultErrorCode,
    AnalysisResultSerializationError,
    SerializedInventoryResult,
)
from repolens_api.inventory.contracts import InventoryResult
from repolens_api.models import Analysis, AnalysisResult, AnalysisStatus, Repository
from repolens_api.services import (
    finalize_analysis_with_result,
    get_analysis_result_record,
    persist_inventory_result,
)


async def _create_analysis(
    sessions: async_sessionmaker[AsyncSession],
    *,
    status: AnalysisStatus,
    processing_token: str | None = None,
) -> Analysis:
    async with sessions() as session:
        repository = Repository(
            canonical_url=f"https://github.com/example/repository-{uuid4()}",
            owner="example",
            name="repository",
        )
        analysis = Analysis(
            repository=repository,
            status=status,
            processing_token=processing_token,
        )
        session.add(analysis)
        await session.commit()
        return analysis


def test_analysis_result_model_round_trips_generic_json_and_schema_version(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(test_sessions, status=AnalysisStatus.COMPLETED)
        payload: dict[str, object] = {"languages": [{"name": "Python"}]}
        async with test_sessions() as session:
            session.add(
                AnalysisResult(
                    analysis_id=analysis.id,
                    schema_version=1,
                    payload=payload,
                )
            )
            await session.commit()

        async with test_sessions() as session:
            persisted = await session.get(AnalysisResult, analysis.id)
            assert persisted is not None
            assert persisted.analysis_id == analysis.id
            assert persisted.schema_version == 1
            assert persisted.payload == payload
            assert persisted.created_at is not None

    asyncio.run(exercise())


def test_analysis_id_primary_key_allows_only_one_result(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(test_sessions, status=AnalysisStatus.COMPLETED)
        async with test_sessions() as session:
            session.add(
                AnalysisResult(
                    analysis_id=analysis.id,
                    schema_version=1,
                    payload={"value": 1},
                )
            )
            await session.commit()

        async with test_sessions() as session:
            session.add(
                AnalysisResult(
                    analysis_id=analysis.id,
                    schema_version=1,
                    payload={"value": 2},
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

    asyncio.run(exercise())


def test_schema_version_must_be_positive(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(test_sessions, status=AnalysisStatus.COMPLETED)
        async with test_sessions() as session:
            session.add(
                AnalysisResult(
                    analysis_id=analysis.id,
                    schema_version=0,
                    payload={"value": 1},
                )
            )
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()

    asyncio.run(exercise())


def test_deleting_analysis_cascades_to_result(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(test_sessions, status=AnalysisStatus.COMPLETED)
        async with test_sessions() as session:
            await session.execute(text("PRAGMA foreign_keys=ON"))
            session.add(
                AnalysisResult(
                    analysis_id=analysis.id,
                    schema_version=1,
                    payload={"value": 1},
                )
            )
            await session.commit()
            await session.execute(delete(Analysis).where(Analysis.id == analysis.id))
            await session.commit()
            assert await session.get(AnalysisResult, analysis.id) is None

    asyncio.run(exercise())


def test_result_reader_returns_none_or_the_single_record(
    test_sessions: async_sessionmaker[AsyncSession],
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(test_sessions, status=AnalysisStatus.COMPLETED)
        async with test_sessions() as session:
            assert await get_analysis_result_record(session, analysis.id) is None
            session.add(
                AnalysisResult(
                    analysis_id=analysis.id,
                    schema_version=1,
                    payload={"value": 1},
                )
            )
            await session.flush()
            assert await get_analysis_result_record(session, analysis.id) is not None

    asyncio.run(exercise())


def test_processing_owner_can_persist_one_result(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="delivery-owner",
        )
        async with test_sessions() as session:
            persisted = await persist_inventory_result(
                session,
                analysis.id,
                "delivery-owner",
                inventory_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            assert persisted is not None
            await session.commit()

        async with test_sessions() as session:
            count = await session.scalar(select(func.count()).select_from(AnalysisResult))
            assert count == 1

    asyncio.run(exercise())


def test_wrong_processing_token_cannot_write_or_change_result(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="delivery-owner",
        )
        async with test_sessions() as session:
            original = await persist_inventory_result(
                session,
                analysis.id,
                "delivery-owner",
                inventory_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            assert original is not None
            await session.commit()
            original_payload = original.payload

        changed_summary = replace(
            inventory_result.repository_summary,
            regular_file_count=99,
        )
        changed_result = replace(
            inventory_result,
            repository_summary=changed_summary,
        )
        async with test_sessions() as session:
            rejected = await persist_inventory_result(
                session,
                analysis.id,
                "another-delivery",
                changed_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            assert rejected is None
            await session.commit()
            persisted = await session.get(AnalysisResult, analysis.id)
            assert persisted is not None
            assert persisted.payload == original_payload

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "status",
    [AnalysisStatus.QUEUED, AnalysisStatus.COMPLETED, AnalysisStatus.FAILED],
)
def test_non_processing_analysis_cannot_persist_result(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
    status: AnalysisStatus,
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=status,
            processing_token="delivery-owner",
        )
        async with test_sessions() as session:
            persisted = await persist_inventory_result(
                session,
                analysis.id,
                "delivery-owner",
                inventory_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            assert persisted is None
            assert await session.get(AnalysisResult, analysis.id) is None

    asyncio.run(exercise())


def test_same_owner_idempotently_updates_the_single_result(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="delivery-owner",
        )
        changed_summary = replace(
            inventory_result.repository_summary,
            regular_file_count=4,
        )
        changed_result = replace(
            inventory_result,
            repository_summary=changed_summary,
        )
        async with test_sessions() as session:
            first = await persist_inventory_result(
                session,
                analysis.id,
                "delivery-owner",
                inventory_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            second = await persist_inventory_result(
                session,
                analysis.id,
                "delivery-owner",
                changed_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            assert first is second
            await session.commit()

        async with test_sessions() as session:
            rows = (await session.scalars(select(AnalysisResult))).all()
            assert len(rows) == 1
            summary = rows[0].payload["repository_summary"]
            assert isinstance(summary, dict)
            assert summary["regular_file_count"] == 4

    asyncio.run(exercise())


def test_persistence_does_not_commit_its_transaction(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="delivery-owner",
        )
        async with test_sessions() as session:
            persisted = await persist_inventory_result(
                session,
                analysis.id,
                "delivery-owner",
                inventory_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            assert persisted is not None
            await session.rollback()

        async with test_sessions() as session:
            assert await session.get(AnalysisResult, analysis.id) is None

    asyncio.run(exercise())


@pytest.mark.parametrize("failure_kind", ["serialization", "size", "schema"])
def test_persistence_failure_writes_no_partial_result(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
    failure_kind: str,
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="delivery-owner",
        )
        result = inventory_result
        max_result_bytes = 10_000
        schema_version = 1
        if failure_kind == "serialization":
            language = replace(result.languages[0], percentage=float("nan"))
            result = replace(result, languages=(language,))
        elif failure_kind == "size":
            max_result_bytes = 1
        else:
            schema_version = 2

        async with test_sessions() as session:
            with pytest.raises(AnalysisResultSerializationError) as raised:
                await persist_inventory_result(
                    session,
                    analysis.id,
                    "delivery-owner",
                    result,
                    schema_version=schema_version,
                    max_result_bytes=max_result_bytes,
                )
            if failure_kind == "size":
                assert raised.value.code is AnalysisResultErrorCode.RESULT_TOO_LARGE
            assert await session.get(AnalysisResult, analysis.id) is None

    asyncio.run(exercise())


def test_finalization_atomically_persists_result_and_completes_analysis(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="delivery-owner",
        )
        async with test_sessions() as session:
            finalized = await finalize_analysis_with_result(
                session,
                analysis.id,
                "delivery-owner",
                inventory_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            assert finalized is True

        async with test_sessions() as session:
            persisted_analysis = await session.get(Analysis, analysis.id)
            persisted_result = await session.get(AnalysisResult, analysis.id)
            assert persisted_analysis is not None
            assert persisted_analysis.status is AnalysisStatus.COMPLETED
            assert persisted_analysis.completed_at is not None
            assert persisted_analysis.processing_token is None
            assert persisted_analysis.error_code is None
            assert persisted_result is not None

    asyncio.run(exercise())


def test_finalization_rejects_stale_token_without_writing(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
) -> None:
    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="current-owner",
        )
        async with test_sessions() as session:
            finalized = await finalize_analysis_with_result(
                session,
                analysis.id,
                "stale-owner",
                inventory_result,
                schema_version=1,
                max_result_bytes=10_000,
            )
            assert finalized is False

        async with test_sessions() as session:
            persisted_analysis = await session.get(Analysis, analysis.id)
            assert persisted_analysis is not None
            assert persisted_analysis.status is AnalysisStatus.PROCESSING
            assert persisted_analysis.processing_token == "current-owner"
            assert await session.get(AnalysisResult, analysis.id) is None

    asyncio.run(exercise())


def test_finalization_database_failure_rolls_back_result_and_completion(
    test_sessions: async_sessionmaker[AsyncSession],
    inventory_result: InventoryResult,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_upsert = services._upsert_prepared_result

    async def fail_after_upsert(
        session: AsyncSession,
        analysis_id: UUID,
        prepared: SerializedInventoryResult,
    ) -> AnalysisResult:
        await original_upsert(session, analysis_id, prepared)
        raise SQLAlchemyError("private database detail")

    monkeypatch.setattr(services, "_upsert_prepared_result", fail_after_upsert)

    async def exercise() -> None:
        analysis = await _create_analysis(
            test_sessions,
            status=AnalysisStatus.PROCESSING,
            processing_token="delivery-owner",
        )
        async with test_sessions() as session:
            with pytest.raises(SQLAlchemyError, match="private database detail"):
                await finalize_analysis_with_result(
                    session,
                    analysis.id,
                    "delivery-owner",
                    inventory_result,
                    schema_version=1,
                    max_result_bytes=10_000,
                )

        async with test_sessions() as session:
            persisted_analysis = await session.get(Analysis, analysis.id)
            assert persisted_analysis is not None
            assert persisted_analysis.status is AnalysisStatus.PROCESSING
            assert persisted_analysis.completed_at is None
            assert persisted_analysis.processing_token == "delivery-owner"
            assert await session.get(AnalysisResult, analysis.id) is None

    asyncio.run(exercise())
