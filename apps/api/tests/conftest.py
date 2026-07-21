"""Shared isolated database and API fixtures."""

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from repolens_api.api import get_analysis_dispatcher
from repolens_api.database import get_session
from repolens_api.main import app
from repolens_api.models import Base


async def _create_schema(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


@pytest.fixture
def test_sessions(tmp_path: Path) -> Iterator[async_sessionmaker[AsyncSession]]:
    database_path = tmp_path / "repolens-test.sqlite3"
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
    asyncio.run(_create_schema(engine))
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    yield sessions

    asyncio.run(engine.dispose())


@pytest.fixture
def dispatched_analysis_ids() -> list[UUID]:
    return []


@pytest.fixture
def api_client(
    test_sessions: async_sessionmaker[AsyncSession],
    dispatched_analysis_ids: list[UUID],
) -> Iterator[TestClient]:
    async def override_session() -> AsyncIterator[AsyncSession]:
        async with test_sessions() as session:
            yield session

    def record_dispatch(analysis_id: UUID) -> None:
        dispatched_analysis_ids.append(analysis_id)

    app.dependency_overrides[get_session] = override_session
    app.dependency_overrides[get_analysis_dispatcher] = lambda: record_dispatch

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
