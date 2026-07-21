"""Asynchronous database engine and session dependencies."""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from repolens_api.settings import get_settings


def create_engine(database_url: str) -> AsyncEngine:
    """Create an asynchronous SQLAlchemy engine for the supplied URL."""
    return create_async_engine(database_url, pool_pre_ping=True)


engine = create_engine(get_settings().database_url)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield one request-scoped asynchronous database session."""
    async with session_factory() as session:
        yield session
