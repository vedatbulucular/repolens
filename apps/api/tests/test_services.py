"""Tests for persistence race handling."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from repolens_api.models import Analysis, Repository
from repolens_api.repository_urls import CanonicalRepository
from repolens_api.services import create_analysis_record


async def _exercise_repository_unique_collision(
    sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, int]:
    identity = CanonicalRepository(
        canonical_url="https://github.com/openai/openai-python",
        owner="openai",
        name="openai-python",
    )
    async with sessions() as seed_session:
        existing_repository = Repository(
            canonical_url=identity.canonical_url,
            owner=identity.owner,
            name=identity.name,
        )
        seed_session.add(existing_repository)
        await seed_session.commit()

    async with sessions() as session:
        scalar_mock = AsyncMock(side_effect=[None, existing_repository])
        monkeypatch.setattr(session, "scalar", scalar_mock)

        analysis = await create_analysis_record(session, identity)

        assert analysis.repository.id == existing_repository.id
        assert scalar_mock.await_count == 2

    async with sessions() as verification_session:
        repository_count = await verification_session.scalar(
            select(func.count()).select_from(Repository)
        )
        analysis_count = await verification_session.scalar(
            select(func.count()).select_from(Analysis)
        )
        return int(repository_count or 0), int(analysis_count or 0)


def test_repository_unique_collision_reuses_committed_record(
    test_sessions: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counts = asyncio.run(_exercise_repository_unique_collision(test_sessions, monkeypatch))

    assert counts == (1, 1)
